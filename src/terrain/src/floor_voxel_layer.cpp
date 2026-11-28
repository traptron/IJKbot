#include <cmath>
#include <unordered_map>

#include "nav2_costmap_2d/cost_values.hpp"
#include "nav2_costmap_2d/voxel_layer.hpp"
#include "pluginlib/class_list_macros.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"

namespace terrain
{
class FloorVoxelLayer : public nav2_costmap_2d::VoxelLayer
{
protected:
  void raytraceFreespace(
    const nav2_costmap_2d::Observation & observation, double * min_x, double * min_y,
    double * max_x, double * max_y) override
  {
    VoxelLayer::raytraceFreespace(observation, min_x, min_y, max_x, max_y);

    const auto & cloud = *observation.cloud_;
    const auto age = (clock_->now() - rclcpp::Time(cloud.header.stamp)).seconds();
    if (cloud.width == 0 || age < 0 || age > 0.5) {
      return;
    }

    // A ray stops short of its endpoint in VoxelLayer. Where multiple returns
    // directly confirm floor, also remove stale low RGB-D marks in that cell.
    // VoxelLayer applies all current obstacle observations after this step.
    std::unordered_map<unsigned int, unsigned int> floor_hits;
    sensor_msgs::PointCloud2ConstIterator<float> x(cloud, "x");
    sensor_msgs::PointCloud2ConstIterator<float> y(cloud, "y");
    sensor_msgs::PointCloud2ConstIterator<float> z(cloud, "z");
    const double range_squared = observation.raytrace_max_range_ * observation.raytrace_max_range_;
    for (; x != x.end(); ++x, ++y, ++z) {
      const double dx = *x - observation.origin_.x;
      const double dy = *y - observation.origin_.y;
      const double dz = *z - observation.origin_.z;
      unsigned int mx, my;
      if (!std::isfinite(*z) || *z < -0.025 || *z > 0.015 ||
        dx * dx + dy * dy + dz * dz > range_squared ||
        !std::isfinite(*x) || !std::isfinite(*y) || !worldToMap(*x, *y, mx, my))
      {
        continue;
      }
      const auto index = getIndex(mx, my);
      if (costmap_[index] != nav2_costmap_2d::LETHAL_OBSTACLE || ++floor_hits[index] != 3) {
        continue;
      }
      // Only clear voxels fully below 7.5 cm. Keep upper obstacles and never
      // write directly into the master map or clear a static or lidar cell.
      for (int mz = 0; mz < size_z_ && origin_z_ + (mz + 1) * z_resolution_ <= 0.07501; ++mz) {
        voxel_grid_.clearVoxel(mx, my, mz);
      }
      if ((voxel_grid_.getData()[index] >> 16) == 0) {
        costmap_[index] = nav2_costmap_2d::FREE_SPACE;
        touch(*x, *y, min_x, min_y, max_x, max_y);
      }
    }
  }
};
}  // namespace terrain

PLUGINLIB_EXPORT_CLASS(terrain::FloorVoxelLayer, nav2_costmap_2d::Layer)
