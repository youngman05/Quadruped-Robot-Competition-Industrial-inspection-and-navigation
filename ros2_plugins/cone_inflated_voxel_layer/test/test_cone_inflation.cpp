#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

#include <gtest/gtest.h>

#include "cone_inflated_voxel_layer/cone_inflated_voxel_layer.hpp"
#include "nav2_costmap_2d/cost_values.hpp"

namespace
{

using cone_inflated_voxel_layer::InflationBounds;
using cone_inflated_voxel_layer::computeInflationCost;
using cone_inflated_voxel_layer::inflateLethalCells;
using cone_inflated_voxel_layer::touchBounds;

std::vector<unsigned char> emptyGrid(unsigned int size_x, unsigned int size_y)
{
  return std::vector<unsigned char>(size_x * size_y, nav2_costmap_2d::FREE_SPACE);
}

unsigned char costAt(
  const std::vector<unsigned char> & grid,
  unsigned int size_x,
  unsigned int x,
  unsigned int y)
{
  return grid[y * size_x + x];
}

void mergeMax(
  const std::vector<unsigned char> & source,
  std::vector<unsigned char> * target)
{
  ASSERT_EQ(source.size(), target->size());
  for (std::size_t index = 0; index < source.size(); ++index) {
    (*target)[index] = std::max((*target)[index], source[index]);
  }
}

TEST(ConeInflationCost, MatchesFoxyFormulaAndBoundaries)
{
  EXPECT_EQ(computeInflationCost(0.0, 0.43, 2.0), nav2_costmap_2d::LETHAL_OBSTACLE);
  EXPECT_EQ(
    computeInflationCost(0.43, 0.43, 2.0),
    nav2_costmap_2d::INSCRIBED_INFLATED_OBSTACLE);
  const auto expected = static_cast<unsigned char>(252.0 * std::exp(-2.0 * 0.17));
  EXPECT_EQ(computeInflationCost(0.60, 0.43, 2.0), expected);
  EXPECT_EQ(cone_inflated_voxel_layer::cellInflationRadius(0.60, 0.05), 12U);
  EXPECT_EQ(cone_inflated_voxel_layer::cellInflationRadius(0.61, 0.05), 13U);
}

TEST(ConeInflationGrid, InflatesAtMapBoundaryWithoutOverflow)
{
  constexpr unsigned int size = 9;
  auto grid = emptyGrid(size, size);
  grid[0] = nav2_costmap_2d::LETHAL_OBSTACLE;
  const auto bounds = inflateLethalCells(
    grid.data(), size, size, 0.05, -1.0, -2.0, 0.20, 0.08, 2.0);
  EXPECT_TRUE(bounds.valid);
  EXPECT_EQ(costAt(grid, size, 0, 0), nav2_costmap_2d::LETHAL_OBSTACLE);
  EXPECT_GT(costAt(grid, size, 3, 0), nav2_costmap_2d::FREE_SPACE);
  EXPECT_EQ(costAt(grid, size, 8, 8), nav2_costmap_2d::FREE_SPACE);
}

TEST(ConeInflationGrid, PreviousHaloBoundsRemainTouchableAfterDisable)
{
  InflationBounds old_bounds;
  old_bounds.valid = true;
  old_bounds.min_x = 1.0;
  old_bounds.min_y = 2.0;
  old_bounds.max_x = 3.0;
  old_bounds.max_y = 4.0;
  double min_x = std::numeric_limits<double>::max();
  double min_y = std::numeric_limits<double>::max();
  double max_x = -std::numeric_limits<double>::max();
  double max_y = -std::numeric_limits<double>::max();
  touchBounds(old_bounds, &min_x, &min_y, &max_x, &max_y);
  EXPECT_DOUBLE_EQ(min_x, 1.0);
  EXPECT_DOUBLE_EQ(min_y, 2.0);
  EXPECT_DOUBLE_EQ(max_x, 3.0);
  EXPECT_DOUBLE_EQ(max_y, 4.0);

  auto disabled_grid = emptyGrid(11, 11);
  const auto no_current_halo = inflateLethalCells(
    disabled_grid.data(), 11, 11, 0.05, 0.0, 0.0, 0.60, 0.43, 2.0);
  EXPECT_FALSE(no_current_halo.valid);
}

TEST(ConeInflationGrid, StaticAndConeInflationStaySourceSpecific)
{
  constexpr unsigned int size_x = 101;
  constexpr unsigned int size_y = 31;
  constexpr double resolution = 0.05;
  auto static_layer = emptyGrid(size_x, size_y);
  auto cone_layer = emptyGrid(size_x, size_y);
  const unsigned int y = 15;
  const unsigned int static_x = 20;
  const unsigned int cone_x = 80;
  static_layer[y * size_x + static_x] = nav2_costmap_2d::LETHAL_OBSTACLE;
  cone_layer[y * size_x + cone_x] = nav2_costmap_2d::LETHAL_OBSTACLE;

  inflateLethalCells(
    static_layer.data(), size_x, size_y, resolution, 0.0, 0.0, 0.30, 0.0, 3.0);
  inflateLethalCells(
    cone_layer.data(), size_x, size_y, resolution, 0.0, 0.0, 0.60, 0.0, 2.0);

  EXPECT_EQ(costAt(static_layer, size_x, static_x + 7, y), nav2_costmap_2d::FREE_SPACE);
  EXPECT_GT(costAt(cone_layer, size_x, cone_x - 11, y), nav2_costmap_2d::FREE_SPACE);
  EXPECT_EQ(costAt(cone_layer, size_x, static_x + 7, y), nav2_costmap_2d::FREE_SPACE);

  auto master = emptyGrid(size_x, size_y);
  mergeMax(static_layer, &master);
  mergeMax(cone_layer, &master);
  EXPECT_EQ(costAt(master, size_x, static_x + 7, y), nav2_costmap_2d::FREE_SPACE);
  EXPECT_GT(costAt(master, size_x, cone_x - 11, y), nav2_costmap_2d::FREE_SPACE);
}

}  // namespace
