#pragma once
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdexcept>
#include <string>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

extern char ** environ;
namespace vision_cpp {
// SSH stdout carries JPEG; stdin carries one acknowledgement per received frame.
class DuplexPipe {
public:
  explicit DuplexPipe(const std::vector<std::string> & arguments) {
    if (arguments.empty()) {throw std::invalid_argument("Empty SSH command");}
    int input[2], output[2];
    if (pipe2(input, O_CLOEXEC) < 0) {throw std::runtime_error("SSH stdin pipe failed");}
    if (pipe2(output, O_CLOEXEC) < 0) {
      close(input[0]); close(input[1]); throw std::runtime_error("SSH stdout pipe failed");
    }
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, input[0], STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&actions, output[1], STDOUT_FILENO);
    for (int fd : {input[0], input[1], output[0], output[1]}) {
      posix_spawn_file_actions_addclose(&actions, fd);
    }
    std::vector<char *> argv;
    for (const auto & argument : arguments) {argv.push_back(const_cast<char *>(argument.c_str()));}
    argv.push_back(nullptr);
    const int error = posix_spawnp(&pid_, argv[0], &actions, nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    close(input[0]); close(output[1]);
    if (error) {
      close(input[1]); close(output[0]); pid_ = -1;
      throw std::runtime_error(std::string("SSH spawn: ") + std::strerror(error));
    }
    input_ = input[1]; output_ = output[0];
    fcntl(output_, F_SETFL, fcntl(output_, F_GETFL) | O_NONBLOCK);
    fcntl(input_, F_SETFL, fcntl(input_, F_GETFL) | O_NONBLOCK);
  }
  ~DuplexPipe() {
    if (input_ >= 0) {close(input_);}
    if (output_ >= 0) {close(output_);}
    if (pid_ < 0) {return;}
    kill(pid_, SIGTERM);
    for (int attempt = 0; attempt < 20; ++attempt) {
      const int result = waitpid(pid_, nullptr, WNOHANG);
      if (result == pid_ || (result < 0 && errno == ECHILD)) {return;}
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    kill(pid_, SIGKILL);
    while (waitpid(pid_, nullptr, 0) < 0 && errno == EINTR) {}
  }
  DuplexPipe(const DuplexPipe &) = delete;
  DuplexPipe & operator=(const DuplexPipe &) = delete;
  int output() const {return output_;}
  void acknowledge() {
    ssize_t count;
    do {count = write(input_, "A", 1);} while (count < 0 && errno == EINTR);
    if (count != 1) {throw std::runtime_error("SSH acknowledgement failed");}
  }
private:
  int pid_ = -1, input_ = -1, output_ = -1;
};
}  // namespace vision_cpp
