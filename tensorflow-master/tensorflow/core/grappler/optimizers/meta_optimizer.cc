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

#include "tensorflow/core/grappler/optimizers/meta_optimizer.h"
#include "tensorflow/core/common_runtime/function.h"
#include "tensorflow/core/framework/function.pb.h"
#include "tensorflow/core/framework/versions.pb.h"
#include "tensorflow/core/grappler/optimizers/arithmetic_optimizer.h"
#include "tensorflow/core/grappler/optimizers/auto_parallel.h"
#include "tensorflow/core/grappler/optimizers/constant_folding.h"
#include "tensorflow/core/grappler/optimizers/custom_graph_optimizer_registry.h"
#include "tensorflow/core/grappler/optimizers/debug_stripper.h"
#include "tensorflow/core/grappler/optimizers/dependency_optimizer.h"
#include "tensorflow/core/grappler/optimizers/experimental_implementation_selector.h"
#include "tensorflow/core/grappler/optimizers/function_optimizer.h"
#include "tensorflow/core/grappler/optimizers/layout_optimizer.h"
#include "tensorflow/core/grappler/optimizers/loop_optimizer.h"
#include "tensorflow/core/grappler/optimizers/memory_optimizer.h"
#include "tensorflow/core/grappler/optimizers/model_pruner.h"
#include "tensorflow/core/grappler/optimizers/pin_to_host_optimizer.h"
#include "tensorflow/core/grappler/optimizers/remapper.h"
#include "tensorflow/core/grappler/optimizers/scoped_allocator_optimizer.h"
#include "tensorflow/core/grappler/optimizers/shape_optimizer.h"
#include "tensorflow/core/grappler/utils/colocation.h"
#include "tensorflow/core/grappler/utils/functions.h"
#include "tensorflow/core/grappler/utils/topological_sort.h"
#include "tensorflow/core/lib/core/status.h"
#include "tensorflow/core/util/ptr_util.h"

namespace tensorflow {
namespace grappler {

namespace {

constexpr int kDefaultNumberOfIterations = 2;
constexpr int kDefaultMinGraphNodes = 4;

int64 NumEdges(const GraphDef& graph) {
  int64 num_edges = 0;
  for (const auto& node : graph.node()) {
    num_edges += node.input_size();
  }
  return num_edges;
}

string PrintSizesBeforeAfter(const GraphDef& before, const GraphDef& after) {
  return strings::StrCat("Graph size after: ", after.node_size(), " nodes (",
                         after.node_size() - before.node_size(), "), ",
                         NumEdges(after), " edges (",
                         NumEdges(after) - NumEdges(before), ")");
}

int NumIterations(const RewriterConfig& cfg) {
  return cfg.meta_optimizer_iterations() == RewriterConfig::DEFAULT_NUM_ITERS
             ? kDefaultNumberOfIterations
             : cfg.meta_optimizer_iterations();
}

// Check if optimizer is allowed to run only once.
bool IsRunOnceOptimizer(const string& name) {
  return name == "layout" || name == "memory_optimizer" ||
         name == "loop_optimizer";
}

// Check if the graphdef contains nodes that indicate TPU execution.
bool IsTPUGraphDef(const GraphDef& def) {
  for (auto node : def.node()) {
    if (node.op() == "TPUCompile" || node.op() == "TPUPartitionedCall") {
      return true;
    }
  }
  return false;
}

}  // namespace

#define MK_OPT(NAME, VALUE) \
  if (optimizer == NAME) return std::unique_ptr<GraphOptimizer>(VALUE)

std::unique_ptr<GraphOptimizer> MetaOptimizer::MakeNewOptimizer(
    const string& optimizer) const {
  MK_OPT("pruning", new ModelPruner());
  MK_OPT("function", new FunctionOptimizer(cfg_.function_optimization()));
  MK_OPT("constfold", new ConstantFolding(cpu_device_));
  MK_OPT("shape", new ShapeOptimizer());
  MK_OPT("remap", new Remapper(cfg_.remapping()));
  MK_OPT("layout", new LayoutOptimizer());
  MK_OPT("memory", new MemoryOptimizer(RewriterConfig::MANUAL));
  MK_OPT("arithmetic", new ArithmeticOptimizer(cfg_.arithmetic_optimization()));
  MK_OPT("autoparallel", new AutoParallel(cfg_.auto_parallel().num_replicas()));
  MK_OPT("loop", new LoopOptimizer(cfg_.loop_optimization(), cpu_device_));
  MK_OPT("dependency", new DependencyOptimizer(cfg_.dependency_optimization()));
  MK_OPT("debug_stripper", new DebugStripper());
  MK_OPT("scoped_allocator",
         new ScopedAllocatorOptimizer(cfg_.scoped_allocator_optimization(),
                                      cfg_.scoped_allocator_opts()));
  MK_OPT("small_op", new PinToHostOptimizer(cfg_.pin_to_host_optimization()));

  return std::unique_ptr<GraphOptimizer>();
}

#undef MK_OPT

Status MetaOptimizer::InitializeOptimizers(
    std::vector<std::unique_ptr<GraphOptimizer>>* optimizers) const {
  if (cfg_.disable_meta_optimizer()) {
    return Status::OK();
  }
  if (!cfg_.disable_model_pruning()) {
    optimizers->push_back(MakeUnique<ModelPruner>());
  }
  if (cfg_.function_optimization() != RewriterConfig::OFF) {
    optimizers->push_back(
        MakeUnique<FunctionOptimizer>(cfg_.function_optimization()));
  }
  if (cfg_.debug_stripper() == RewriterConfig::ON) {
    optimizers->push_back(MakeUnique<DebugStripper>());
  }
  if (cfg_.constant_folding() != RewriterConfig::OFF) {
    optimizers->push_back(
        MakeUnique<ConstantFolding>(cfg_.constant_folding(), cpu_device_));
  }
  if (cfg_.shape_optimization() != RewriterConfig::OFF) {
    optimizers->push_back(MakeUnique<ShapeOptimizer>());
  }
  if (cfg_.remapping() != RewriterConfig::OFF) {
    optimizers->push_back(MakeUnique<Remapper>(cfg_.remapping()));
  }
  if (cfg_.pin_to_host_optimization() != RewriterConfig::OFF) {
    optimizers->push_back(MakeUnique<PinToHostOptimizer>());
  }
  if (cfg_.arithmetic_optimization() != RewriterConfig::OFF) {
    optimizers->push_back(
        MakeUnique<ArithmeticOptimizer>(cfg_.arithmetic_optimization()));
  }
  if (cfg_.loop_optimization() != RewriterConfig::OFF) {
    optimizers->push_back(
        MakeUnique<LoopOptimizer>(cfg_.loop_optimization(), cpu_device_));
  }
  if (cfg_.dependency_optimization() != RewriterConfig::OFF) {
    optimizers->push_back(
        MakeUnique<DependencyOptimizer>(cfg_.dependency_optimization()));
  }
  if (cfg_.layout_optimizer() != RewriterConfig::OFF) {
    optimizers->push_back(MakeUnique<LayoutOptimizer>());
  }
  if (cfg_.memory_optimization() != RewriterConfig::NO_MEM_OPT) {
    if (cfg_.memory_optimizer_target_node_name_scope().empty()) {
      optimizers->push_back(
          // Use the default target node name prefix "gradients/"
          MakeUnique<MemoryOptimizer>(cfg_.memory_optimization()));
    } else {
      optimizers->push_back(MakeUnique<MemoryOptimizer>(
          cfg_.memory_optimization(),
          cfg_.memory_optimizer_target_node_name_scope()));
    }
  }
  if (cfg_.auto_parallel().enable()) {
    optimizers->push_back(
        MakeUnique<AutoParallel>(cfg_.auto_parallel().num_replicas()));
  }
  if (cfg_.scoped_allocator_optimization()) {
    optimizers->push_back(MakeUnique<ScopedAllocatorOptimizer>(
        cfg_.scoped_allocator_optimization(), cfg_.scoped_allocator_opts()));
  }
  return InitializeCustomGraphOptimizers(std::set<string>(), optimizers);
}

Status MetaOptimizer::InitializeOptimizersByName(
    std::vector<std::unique_ptr<GraphOptimizer>>* optimizers) const {
  std::set<string> initialized_custom_optimizers;
  for (const string& optimizer_name : cfg_.optimizers()) {
    auto optimizer = MakeNewOptimizer(optimizer_name);
    if (optimizer) {
      VLOG(2) << "Registered default graph optimizer: " << optimizer_name;
      optimizers->push_back(std::move(optimizer));
      continue;
    }

    auto custom_optimizer =
        CustomGraphOptimizerRegistry::CreateByNameOrNull(optimizer_name);

    if (custom_optimizer) {
      VLOG(2) << "Registered custom graph optimizer: " << optimizer_name;
      TF_RETURN_IF_ERROR(custom_optimizer->Init(
          GetCustomGraphOptimizerConfig(optimizer_name)));
      optimizers->push_back(std::move(custom_optimizer));
      initialized_custom_optimizers.insert(optimizer_name);
    } else {
      VLOG(2) << "Can't register an optimizer by name: " << optimizer_name;
    }
  }
  return InitializeCustomGraphOptimizers(initialized_custom_optimizers,
                                         optimizers);
}

Status MetaOptimizer::InitializeCustomGraphOptimizers(
    const std::set<string>& pre_initialized_optimizers,
    std::vector<std::unique_ptr<GraphOptimizer>>* optimizers) const {
  for (const auto& optimizer_config : cfg_.custom_optimizers()) {
    if (pre_initialized_optimizers.find(optimizer_config.name()) !=
        pre_initialized_optimizers.end()) {
      continue;
    }
    // Initialize the ExperimentalImplementationSelector here instead of
    // CustomizeOptimizer registry, due the static link issue in TensorRT for
    // double registry.
    // TODO(laigd): Remove this hack and change it back to use the registry once
    // the duplicate static import issue is fixed.
    std::unique_ptr<CustomGraphOptimizer> custom_optimizer;
    if (optimizer_config.name() == "ExperimentalImplementationSelector") {
      custom_optimizer.reset(new ExperimentalImplementationSelector());
    } else {
      custom_optimizer = CustomGraphOptimizerRegistry::CreateByNameOrNull(
          optimizer_config.name());
    }
    if (custom_optimizer) {
      VLOG(2) << "Registered custom configurable graph optimizer: "
              << optimizer_config.name();
      TF_RETURN_IF_ERROR(custom_optimizer->Init(&optimizer_config));
      optimizers->push_back(std::move(custom_optimizer));
    } else {
      // If there are no custom optimizers with given name, try to initalize a
      // default optimizer. This way, custom configurable optimizers can be
      // mixed with default optimizers in any order.
      auto optimizer = MakeNewOptimizer(optimizer_config.name());
      if (optimizer) {
        VLOG(2) << "Registered default graph optimizer: "
                << optimizer_config.name();
        optimizers->push_back(std::move(optimizer));
        continue;
      }
      VLOG(2) << "Can't register an optimizer by name: "
              << optimizer_config.name();
    }
  }
  return Status::OK();
}

const RewriterConfig::CustomGraphOptimizer*
MetaOptimizer::GetCustomGraphOptimizerConfig(const string& name) const {
  for (const auto& config : cfg_.custom_optimizers()) {
    if (config.name() == name) {
      return &config;
    }
  }
  return nullptr;
}

Status MetaOptimizer::OptimizeGraph(Cluster* cluster, const GrapplerItem& item,
                                    GraphDef* optimized_graph) {
  int min_graph_nodes = cfg_.min_graph_nodes() == 0 ? kDefaultMinGraphNodes
                                                    : cfg_.min_graph_nodes();
  if (item.graph.node_size() < min_graph_nodes) {
    VLOG(3) << "Skipping optimization, graph has less than " << min_graph_nodes
            << " nodes.";
    *optimized_graph = item.graph;
    return Status::OK();
  }

  std::vector<std::unique_ptr<GraphOptimizer>> optimizers;
  if (cfg_.optimizers().empty()) {
    TF_RETURN_IF_ERROR(InitializeOptimizers(&optimizers));
  } else {
    TF_RETURN_IF_ERROR(InitializeOptimizersByName(&optimizers));
  }

  VLOG(2) << "Optimize GrapplerItem: item.id=" << item.id
          << " num_optimizers=" << optimizers.size()
          << ", num nodes = " << item.graph.node_size();

  if (optimizers.empty()) {
    VLOG(3) << "Skipping graph optimization, no optimizers registered";
    *optimized_graph = item.graph;
    return Status::OK();
  }

  // Invariant: optimized_graph contains the most recently optimized version of
  // the graph.
  GrapplerItem optimized_item = item;
  optimized_graph->Swap(&optimized_item.graph);

  bool is_optimized = false;
  GraphOptimizationResult optimization_result(item.id);
  GraphOptimizer* fusion_optimizer = nullptr;
  GraphOptimizer* sa_optimizer = nullptr;

  for (int iteration = 0; iteration < NumIterations(cfg_); ++iteration) {
    // Don't bother optimizing further if the graph is already tiny.
    if (optimized_graph->node_size() < min_graph_nodes) {
      VLOG(3) << "Stopping after iteration " << iteration
              << ", graph is tiny (#nodes = " << optimized_graph->node_size()
              << "  < " << min_graph_nodes << ")";
      break;
    }

    VLOG(4) << "Starting optimization iteration " << iteration;
    for (const auto& optimizer : optimizers) {
      // Some optimizers can run only once.
      if (iteration > 0 && IsRunOnceOptimizer(optimizer->name())) continue;
      // Some must run only on the last iteration.
      if (optimizer->name() == "scoped_allocator_optimizer") {
        if (sa_optimizer == nullptr) sa_optimizer = optimizer.get();
        continue;
      }
      if (optimizer->name() == "xla-fusion") {
        if (fusion_optimizer == nullptr) fusion_optimizer = optimizer.get();
        continue;
      }
      Status status = RunOptimizer(optimizer.get(), cluster, &optimized_item,
                                   optimized_graph, &optimization_result);
      if (status.ok()) is_optimized = true;
    }
  }

  // Run fusion optimizer if requested after all other optimizers since: 1) it
  // doesn't need to be called more than once. 2) we don't want subsequent
  // optimization passes to break the fusion clusters. We could potentially
  // encapsulate the fusion clusters right away, but that will prevent a lot of
  // optimizations from taking place since we don't have shape inference for
  // functions, and we can't optimize across function boundaries.
  if (fusion_optimizer != nullptr) {
    Status status = RunOptimizer(fusion_optimizer, cluster, &optimized_item,
                                 optimized_graph, &optimization_result);
    if (status.ok()) is_optimized = true;
  }

  // ScopedAllocatorOptimizer must run last.
  if (sa_optimizer != nullptr) {
    Status status = RunOptimizer(sa_optimizer, cluster, &optimized_item,
                                 optimized_graph, &optimization_result);
    if (status.ok()) is_optimized = true;
  }

  // Record graph optimization result.
  optimization_results_.push_back(optimization_result);

  if (is_optimized) {
    TF_RETURN_IF_ERROR(TopologicalSort(optimized_graph));
    ReassignColocation(optimized_graph);
    // Make sure that the optimizers preserved the graph version.
    DCHECK_EQ(optimized_graph->versions().producer(),
              item.graph.versions().producer());
  }

  return Status::OK();
}

Status MetaOptimizer::RunOptimizer(
    GraphOptimizer* optimizer, Cluster* cluster, GrapplerItem* optimized_item,
    GraphDef* optimized_graph, GraphOptimizationResult* optimization_result) {
  uint64 start_us = Env::Default()->NowMicros();
  // This swaps the current optimized_graph into optimized item and
  // resets optimized_graph to an empty graph.
  optimized_graph->Swap(&optimized_item->graph);
  *optimized_graph = GraphDef();
  Status status =
      optimizer->Optimize(cluster, *optimized_item, optimized_graph);
  uint64 end_us = Env::Default()->NowMicros();

  string result;
  if (!status.ok()) {
    optimized_graph->Swap(&optimized_item->graph);
    result = status.ToString();
  } else {
    float duration_ms = (end_us - start_us) / 1000.0f;
    result = strings::StrCat(
        PrintSizesBeforeAfter(optimized_item->graph, *optimized_graph),
        ", time = ", duration_ms, "ms.");
  }
  VLOG(1) << optimizer->name() << ": " << result;

  OptimizerResult optimizer_result{optimizer->name(), result};
  optimization_result->results.push_back(optimizer_result);
  return status;
}

Status MetaOptimizer::Optimize(Cluster* cluster, const GrapplerItem& item,
                               GraphDef* optimized_graph) {
  VLOG(1) << "Starting optimization for grappler item: " << item.id;
  optimization_results_.clear();

  // 1. Optimize main graph
  TF_RETURN_IF_ERROR(OptimizeGraph(cluster, item, optimized_graph));
  VLOG(1) << "Optimized main graph.";

  // Skip optimizing functions if this is a TPU graph. Currently, Grappler
  // passes do not handle TPU functions correctly in a variety of ways (Note
  // that due to the pre-placement TPU graph rewriting passes, the TPU-related
  // ops are encapsulated away into functions). For example, TPU graphs contain
  // TPUReplicateMetadata node that carries relevant TPU metadata and Grappler
  // passes could prune that away. Grappler passes could also cause issues
  // around shape inference. Since the desired and existing behavior is to not
  // optimize TPU functions with Grappler, this check preserves that.
  if (IsTPUGraphDef(*optimized_graph)) {
    VLOG(2) << "Skipping optimizing funcs for TPU graphs";
    return Status::OK();
  }

  // 2. Optimize function library
  FunctionLibraryDefinition flib(OpRegistry::Global(),
                                 optimized_graph->library());

  // Optimize each function only once.
  std::unordered_set<string> optimized_funcs;
  bool optimize_function_library = true;

  while (optimize_function_library) {
    optimize_function_library = false;

    for (const FunctionDef& func : optimized_graph->library().function()) {
      const string& func_name = func.signature().name();

      // Skip already optimized functions.
      if (optimized_funcs.find(func_name) != optimized_funcs.end()) continue;

      // Skip parametrized functions (function type or body is defined only at
      // function call time by caller node attributes).
      if (IsParametrized(func)) continue;

      VLOG(3) << "Optimize function: function=" << func_name;

      // Function optimization might specialize nested function calls, so we
      // have to reset the flag and do at least one more pass over the library.
      optimize_function_library = true;
      optimized_funcs.insert(func_name);

      // Make a GrapplerItem from a FunctionDef.
      GrapplerFunctionItem func_item;
      TF_RETURN_IF_ERROR(MakeGrapplerFunctionItem(
          func, flib, item.graph.versions().producer(), &func_item));

      // Optimize function body graph.
      GraphDef optimized_func_graph;
      TF_RETURN_IF_ERROR(
          OptimizeGraph(cluster, func_item, &optimized_func_graph));

      // Function body optimization might have created new specialized
      // functions for each instantiation context. Add them to the library.
      for (const FunctionDef& func_def :
           optimized_func_graph.library().function()) {
        if (flib.Find(func_def.signature().name()) == nullptr) {
          TF_RETURN_IF_ERROR(flib.AddFunctionDef(func_def));
        }
      }

      // Convert optimized graph back to FunctionDef.
      FunctionDef optimized_func;
      func_item.SwapFunctionBody(std::move(optimized_func_graph));
      TF_RETURN_IF_ERROR(MakeFunctionDef(func_item, flib, &optimized_func));

      // Replace optimized function with a new FunctionDef.
      TF_RETURN_IF_ERROR(flib.ReplaceFunction(func_name, optimized_func));
    }

    // If optimized at least one function, update the graph library.
    if (optimize_function_library) {
      *optimized_graph->mutable_library() = flib.ToProto();
    }
  }

  VLOG(1) << "Optimized " << optimized_funcs.size()
          << " functions: " << str_util::Join(optimized_funcs, ", ");

  return Status::OK();
}

void MetaOptimizer::PrintResult() {
  for (const GraphOptimizationResult& graph_result : optimization_results_) {
    LOG(INFO) << "Optimization results for grappler item: " << graph_result.id;
    for (const OptimizerResult& result : graph_result.results) {
      LOG(INFO) << "  " << result.optimizer_name << ": " << result.result;
    }
  }
}

void MetaOptimizer::Feedback(Cluster* cluster, const GrapplerItem& item,
                             const GraphDef& pruned_graph, double result) {
  // Nothing to do for MetaOptimizer.
}

bool MetaOptimizerEnabled(const RewriterConfig& cfg) {
  if (cfg.disable_meta_optimizer()) {
    return false;
  }
  return !cfg.disable_model_pruning() ||
         cfg.layout_optimizer() != RewriterConfig::OFF ||
         cfg.function_optimization() != RewriterConfig::OFF ||
         cfg.constant_folding() != RewriterConfig::OFF ||
         cfg.shape_optimization() != RewriterConfig::OFF ||
         cfg.remapping() != RewriterConfig::OFF ||
         cfg.arithmetic_optimization() != RewriterConfig::OFF ||
         cfg.loop_optimization() != RewriterConfig::OFF ||
         cfg.dependency_optimization() != RewriterConfig::OFF ||
         cfg.auto_parallel().enable() ||
         cfg.memory_optimization() != RewriterConfig::NO_MEM_OPT ||
         cfg.debug_stripper() == RewriterConfig::ON ||
         cfg.scoped_allocator_optimization() == RewriterConfig::ON ||
         cfg.pin_to_host_optimization() != RewriterConfig::OFF ||
         !cfg.optimizers().empty() || !cfg.custom_optimizers().empty();
}

Status RunMetaOptimizer(const GrapplerItem& item, const RewriterConfig& cfg,
                        DeviceBase* cpu_device, Cluster* cluster,
                        GraphDef* optimized_graph) {
  MetaOptimizer optimizer(cpu_device, cfg);
  return optimizer.Optimize(cluster, item, optimized_graph);
}

}  // namespace grappler
}  // namespace tensorflow
