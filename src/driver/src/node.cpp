#include "node.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <termios.h>


STS3215Node::STS3215Node()
    : Node("sts3215_node"),
      serial_("/dev/ttyACM0", B1000000),
      servo_(serial_)
{
     RCLCPP_INFO(
        get_logger(),
        "Configuring STS3215 ID=%d",
        static_cast<int>(SERVO_ID)
    );

    servo_.enableWheelMode(SERVO_ID);

    RCLCPP_INFO(
        get_logger(),
        "Wheel mode enabled"
    );
}


void STS3215Node::runTerminalTest()
{
    std::cout
        << "\nSTS3215 speed test\n"
        << "------------------\n"
        << "Speed range: "
        << -STS3215::MAX_SPEED
        << " ... "
        << STS3215::MAX_SPEED
        << "\n"
        << "q - quit\n\n";


    std::string input;


    while (rclcpp::ok())
    {
        std::cout << "speed> " << std::flush;


        if (!std::getline(std::cin, input))
        {
            break;
        }


        if (input == "q" ||
            input == "Q")
        {
            break;
        }


        try
        {
            std::size_t position = 0;

            int speed = std::stoi(
                input,
                &position
            );


            /*
             * Не разрешаем:
             *
             * 1000abc
             */

            if (position != input.size())
            {
                std::cout
                    << "Invalid input\n";

                continue;
            }


            if (speed < -STS3215::MAX_SPEED ||
                speed > STS3215::MAX_SPEED)
            {
                std::cout
                    << "Speed must be between "
                    << -STS3215::MAX_SPEED
                    << " and "
                    << STS3215::MAX_SPEED
                    << '\n';

                continue;
            }


            servo_.setSpeed(
                SERVO_ID,
                static_cast<int16_t>(speed)
            );


            std::cout
                << "Speed set: "
                << speed
                << '\n';
        }
        catch (const std::invalid_argument&)
        {
            std::cout
                << "Invalid number\n";
        }
        catch (const std::out_of_range&)
        {
            std::cout
                << "Number out of range\n";
        }
    }


    /*
     * При нормальном выходе обязательно
     * отправляем speed = 0.
     */

    std::cout
        << "\nStopping servo...\n";

    servo_.stop(SERVO_ID);
}


/*
 * ============================================================
 * main
 * ============================================================
 */

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);

    try
    {
        auto node =
            std::make_shared<STS3215Node>();


        /*
         * Сейчас тестируем через терминал.
         *
         * Позже здесь будет:
         *
         * rclcpp::spin(node);
         */

        node->runTerminalTest();


        rclcpp::shutdown();

        return 0;
    }
    catch (const std::exception& e)
    {
        std::cerr
            << "Fatal error: "
            << e.what()
            << '\n';

        rclcpp::shutdown();

        return 1;
    }
}