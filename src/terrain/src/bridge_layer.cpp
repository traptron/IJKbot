#include <algorithm>
#include <chrono>
#include <cmath>
#include <mutex>
#include <stdexcept>

#include "nav2_costmap_2d/cost_values.hpp"
#include "nav2_costmap_2d/layer.hpp"
#include "nav2_costmap_2d/layered_costmap.hpp"
#include "nav_msgs/msg/occupancy_grid.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace terrain
{
class BridgeLayer : public nav2_costmap_2d::Layer
{
public:
  void onInitialize() override
  {
    auto node = node_.lock();
    if (!node || layered_costmap_->getGlobalFrameID() != "map") {
      throw std::runtime_error("BridgeLayer requires a costmap in the map frame");
    }
    declareParameter("block_unobserved", rclcpp::ParameterValue(true));
    node->get_parameter(name_ + ".block_unobserved", block_unobserved_);
    clock_ = node->get_clock();
    current_ = false;
    enabled_ = true;
    rclcpp::SubscriptionOptions options;
    options.callback_group = callback_group_;
    subscription_ = node->create_subscription<nav_msgs::msg::OccupancyGrid>(
      "/terrain/grid", rclcpp::QoS(1).reliable().transient_local(),
      [this](nav_msgs::msg::OccupancyGrid::ConstSharedPtr grid) {
        const auto & info = grid->info;
        const auto & q = info.origin.orientation;
        const auto age = (clock_->now() - rclcpp::Time(grid->header.stamp)).seconds();
        if (grid->header.frame_id != "map" || !info.width || !info.height ||
          !std::isfinite(info.resolution) || info.resolution <= 0 ||
          !std::isfinite(info.origin.position.x) || !std::isfinite(info.origin.position.y) ||
          q.x != 0 || q.y != 0 || q.z != 0 || q.w != 1 ||
          grid->data.size() != static_cast<size_t>(info.width) * info.height ||
          age < 0 || age > max_age_)
        {
          return;
        }
        std::lock_guard<std::mutex> lock(mutex_);
        grid_ = grid;
        received_ = std::chrono::steady_clock::now();
      }, options);
  }

  void updateBounds(
    double, double, double, double * min_x, double * min_y, double * max_x,
    double * max_y) override
  {
    std::lock_guard<std::mutex> lock(mutex_);
    cycle_grid_ = grid_;
    current_ = cycle_grid_ != nullptr;
    if (!cycle_grid_) {
      return;
    }
    const auto age = (clock_->now() - rclcpp::Time(cycle_grid_->header.stamp)).seconds();
    stale_ = std::chrono::duration<double>(std::chrono::steady_clock::now() -
      received_).count() > max_age_ || age < 0 || age > max_age_;
    const auto & info = cycle_grid_->info;
    *min_x = std::min(*min_x, info.origin.position.x);
    *min_y = std::min(*min_y, info.origin.position.y);
    *max_x = std::max(*max_x, info.origin.position.x + info.width * info.resolution);
    *max_y = std::max(*max_y, info.origin.position.y + info.height * info.resolution);
  }

  void updateCosts(
    nav2_costmap_2d::Costmap2D & master, int min_i, int min_j, int max_i, int max_j) override
  {
    if (!cycle_grid_) {
      return;
    }
    const auto & info = cycle_grid_->info;
    for (int y = min_j; y < max_j; ++y) {
      for (int x = min_i; x < max_i; ++x) {
        double wx, wy;
        master.mapToWorld(x, y, wx, wy);
        int ix = static_cast<int>(std::floor((wx - info.origin.position.x) / info.resolution));
        int iy = static_cast<int>(std::floor((wy - info.origin.position.y) / info.resolution));
        // Include every fine grid cell overlapping the costmap cell. Sampling just the
        // center can miss a small obstruction between Nav2 cells.
        const double half = master.getResolution() / 2;
        const int radius = static_cast<int>(std::ceil(half / info.resolution));
        int risk = -1;
        for (int sy = std::max(0, iy - radius); sy <= iy + radius && sy < int(info.height); ++sy) {
          for (int sx = std::max(0, ix - radius); sx <= ix + radius && sx < int(info.width); ++sx) {
            const double reach = half + info.resolution / 2;
            if (std::abs(info.origin.position.x + (sx + .5) * info.resolution - wx) >= reach ||
              std::abs(info.origin.position.y + (sy + .5) * info.resolution - wy) >= reach)
            {
              continue;
            }
            const auto value = cycle_grid_->data[static_cast<size_t>(sy) * info.width + sx];
            risk = std::max(risk, stale_ && value >= 0 ? std::max<int>(value, 50) : value);
          }
        }
        if (risk >= 100 || (risk >= 50 && block_unobserved_)) {
          master.setCost(x, y, nav2_costmap_2d::LETHAL_OBSTACLE);
        } else if (risk >= 50 && master.getCost(x, y) < 200) {
          master.setCost(x, y, 200);
        }
      }
    }
  }

  void reset() override {}  // Clearing costmaps must preserve the safety overlay.
  bool isClearable() override {return false;}

private:
  static constexpr double max_age_ = .5;
  bool block_unobserved_{true};
  bool stale_{true};
  std::mutex mutex_;
  std::chrono::steady_clock::time_point received_;
  rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr subscription_;
  nav_msgs::msg::OccupancyGrid::ConstSharedPtr grid_;
  nav_msgs::msg::OccupancyGrid::ConstSharedPtr cycle_grid_;
};
}  // namespace terrain

PLUGINLIB_EXPORT_CLASS(terrain::BridgeLayer, nav2_costmap_2d::Layer)
