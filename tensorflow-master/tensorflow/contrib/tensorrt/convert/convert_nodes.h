/* Copyright 2018 The TensorFlow Authors. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/

#ifndef TENSORFLOW_CONTRIB_TENSORRT_CONVERT_CONVERT_NODES_H_
#define TENSORFLOW_CONTRIB_TENSORRT_CONVERT_CONVERT_NODES_H_

#include <set>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "tensorflow/contrib/tensorrt/convert/utils.h"
#include "tensorflow/contrib/tensorrt/log/trt_logger.h"
#include "tensorflow/contrib/tensorrt/resources/trt_allocator.h"
#include "tensorflow/contrib/tensorrt/resources/trt_int8_calibrator.h"
#include "tensorflow/core/framework/graph.pb.h"
#include "tensorflow/core/graph/graph.h"
#include "tensorflow/core/grappler/costs/graph_properties.h"
#include "tensorflow/core/lib/core/status.h"

#if GOOGLE_CUDA
#if GOOGLE_TENSORRT

namespace tensorflow {
namespace tensorrt {
extern const char* const kInputPHName;
extern const char* const kOutputPHName;

namespace convert {

struct EngineConnection {
  // Constructs a non-control edge.
  EngineConnection(const string& outside, int out_id, int out_port,
                   const string& inside, int in_id, int in_port,
                   bool input_edge, int port)
      : outside_node_name(outside),
        outside_id(out_id),
        outside_port(out_port),
        inside_node_name(inside),
        inside_id(in_id),
        inside_port(in_port),
        is_input_edge(input_edge),
        port_number(port) {}

  // Constructs a control edge.
  EngineConnection(const string& outside, int out_id, const string& inside,
                   int in_id, bool input_edge)
      : outside_node_name(outside),
        outside_id(out_id),
        outside_port(Graph::kControlSlot),
        inside_node_name(inside),
        inside_id(in_id),
        inside_port(Graph::kControlSlot),
        is_input_edge(input_edge),
        port_number(Graph::kControlSlot) {}

  bool is_control_edge() const { return port_number == Graph::kControlSlot; }

  const string outside_node_name;
  const int outside_id;
  const int outside_port;
  tensorflow::PartialTensorShape outside_shape;  // Only set for input edge.

  const string inside_node_name;
  const int inside_id;
  const int inside_port;
  tensorflow::PartialTensorShape inside_shape;  // Only set for output edge.

  tensorflow::DataType connection_type;
  const bool is_input_edge;

  // The port number of the TRT node connected with this edge.
  const int port_number;
};

struct EngineInfo {
  EngineInfo()
      : engine_type(EngineType::TRTStatic),
        max_workspace_size_bytes(0),
        precision_mode(FP32MODE) {}

  string engine_name;
  string device;
  tensorflow::GraphDef segment_graph_def;

  // Non-control input connections inside this vector are sorted in a way such
  // that, the segment nodes connecting to them are topological sorted.
  // In addition, for non-control connections, there must be no duplicates.
  std::vector<EngineConnection> connections;

  enum class EngineType { TRTStatic = 0, TRTDynamic = 1 };
  EngineType engine_type;
  int64 max_workspace_size_bytes;
  int maximum_cached_engines;
  std::vector<int> cached_engine_batches;
  int precision_mode;
};

// Constructs a graphdef from the segment in the given graph. Adds placeholder
// nodes for input edges (InputPH_*) and identity nodes for output edges
// (OutputPH_*). This function needs to be called before TensorRT nodes
// inserted in order to correctly get sizes from the original graph.
//
// - subgraph_node_names: the node names of the subgraph.
// - subgraph_node_ids: the node ids of the subgraph, must be sorted in
//   topological order.
// - segment_def: the output GraphDef, whose non-input/output nodedefs will be
//   sorted in topological order.
//
// TODO(aaroey): add tests to validate these properties.
tensorflow::Status ConvertSegmentToGraphDef(
    const tensorflow::Graph* graph,
    const tensorflow::grappler::GraphProperties& graph_properties,
    const std::set<string>& subgraph_node_names,
    const std::vector<int>& subgraph_node_ids,
    std::vector<EngineConnection>* connections,
    tensorflow::GraphDef* segment_def, string* common_scope);

// Converts given subgraph to a TRT engine saved in 'engine'. Returns ok iff
// 'builder' successfully build the engine. If the result is not ok, 'engine'
// will be set to nullptr
// Once returned, 'builder' is not needed any more and can be safely detroyed.
//
// - convert_successfully: indicates whether the converson to TensorRT network
//   is successful. This is different than successfully building the engine:
//   building can still fail afterwards.
tensorflow::Status ConvertGraphDefToEngine(
    const tensorflow::GraphDef& gdef, int precision_mode, int max_batch_size,
    size_t max_workspace_size_bytes,
    const std::vector<tensorflow::PartialTensorShape>& input_shapes,
    Logger* logger, nvinfer1::IGpuAllocator* allocator,
    TRTInt8Calibrator* calibrator,
    TrtUniquePtrType<nvinfer1::ICudaEngine>* engine,
    bool* convert_successfully);

// Helper class for the segmenter to determine whether an input edge to the TRT
// segment is valid.
class InputEdgeValidator {
 public:
  InputEdgeValidator(const grappler::GraphProperties& graph_properties)
      : graph_properties_(graph_properties) {}

  // Return true if the specified edge is eligible to be an input edge of the
  // TRT segment.
  bool operator()(const tensorflow::Edge* in_edge) const;

 private:
  const grappler::GraphProperties& graph_properties_;
};

// Helper class for the segmenter to determine whether an output edge from the
// TRT segment is valid.
class OutputEdgeValidator {
 public:
  // Return true if the specified edge is eligible to be an output edge of the
  // TRT segment.
  bool operator()(const tensorflow::Edge* out_edge) const;
};

}  // namespace convert
}  // namespace tensorrt
}  // namespace tensorflow

#endif  // GOOGLE_TENSORRT
#endif  // GOOGLE_CUDA

#endif  // TENSORFLOW_CONTRIB_TENSORRT_CONVERT_CONVERT_NODES_H_
