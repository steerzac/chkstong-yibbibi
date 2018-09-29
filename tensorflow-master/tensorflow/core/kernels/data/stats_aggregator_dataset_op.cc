/* Copyright 2017 The TensorFlow Authors. All Rights Reserved.

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
#include "tensorflow/core/framework/partial_tensor_shape.h"
#include "tensorflow/core/framework/stats_aggregator.h"
#include "tensorflow/core/framework/tensor.h"
#include "tensorflow/core/kernels/data/dataset.h"
#include "tensorflow/core/lib/random/random.h"

namespace tensorflow {
namespace data {
namespace {

class SetStatsAggregatorDatasetOp : public UnaryDatasetOpKernel {
 public:
  explicit SetStatsAggregatorDatasetOp(OpKernelConstruction* ctx)
      : UnaryDatasetOpKernel(ctx) {}

  void MakeDataset(OpKernelContext* ctx, DatasetBase* input,
                   DatasetBase** output) override {
    StatsAggregatorResource* stats_aggregator_resource;
    OP_REQUIRES_OK(ctx, LookupResource(ctx, HandleFromInput(ctx, 1),
                                       &stats_aggregator_resource));
    core::ScopedUnref unref_stats_aggregator(stats_aggregator_resource);

    *output = new Dataset(ctx, input, ctx->input(1), stats_aggregator_resource);
  }

 private:
  class Dataset : public DatasetBase {
   public:
    explicit Dataset(OpKernelContext* ctx, const DatasetBase* input,
                     const Tensor& resource_handle,
                     StatsAggregatorResource* stats_aggregator_resource)
        : DatasetBase(DatasetContext(ctx)),
          input_(input),
          resource_handle_(resource_handle),
          stats_aggregator_resource_(stats_aggregator_resource) {
      input_->Ref();
      stats_aggregator_resource_->Ref();
    }

    ~Dataset() override {
      input_->Unref();
      stats_aggregator_resource_->Unref();
    }

    std::unique_ptr<IteratorBase> MakeIteratorInternal(
        const string& prefix) const override {
      return std::unique_ptr<IteratorBase>(new Iterator(
          {this, strings::StrCat(prefix, "::SetStatsAggregator")}));
    }

    const DataTypeVector& output_dtypes() const override {
      return input_->output_dtypes();
    }
    const std::vector<PartialTensorShape>& output_shapes() const override {
      return input_->output_shapes();
    }

    string DebugString() const override {
      return "SetStatsAggregatorDatasetOp::Dataset";
    }

   protected:
    Status AsGraphDefInternal(SerializationContext* ctx,
                              DatasetGraphDefBuilder* b,
                              Node** output) const override {
      Node* input_graph_node = nullptr;
      TF_RETURN_IF_ERROR(b->AddInputDataset(ctx, input_, &input_graph_node));
      Node* resource_handle_node = nullptr;
      TF_RETURN_IF_ERROR(b->AddTensor(resource_handle_, &resource_handle_node));
      TF_RETURN_IF_ERROR(b->AddDataset(
          this, {input_graph_node, resource_handle_node}, output));
      return Status::OK();
    }

   private:
    class Iterator : public DatasetIterator<Dataset> {
     public:
      explicit Iterator(const Params& params)
          : DatasetIterator<Dataset>(params) {}

      Status Initialize(IteratorContext* ctx) override {
        return dataset()->input_->MakeIterator(ctx, prefix(), &input_impl_);
      }

      Status GetNextInternal(IteratorContext* ctx,
                             std::vector<Tensor>* out_tensors,
                             bool* end_of_sequence) override {
        mutex_lock l(mu_);
        StatsAggregatorResource* stats_aggregator_resource =
            dataset()->stats_aggregator_resource_;
        IteratorContext::Params params;
        params.env = ctx->env();
        params.runner = *(ctx->runner());
        params.stats_aggregator_getter = [stats_aggregator_resource]() {
          return stats_aggregator_resource->stats_aggregator();
        };
        params.lib = ctx->lib();
        params.function_library = ctx->function_library();
        params.allocator_getter = ctx->allocator_getter();
        IteratorContext set_stats_aggregator_ctx(params);
        return input_impl_->GetNext(&set_stats_aggregator_ctx, out_tensors,
                                    end_of_sequence);
      }

     protected:
      Status SaveInternal(IteratorStateWriter* writer) override {
        return errors::Unimplemented(dataset()->DebugString(),
                                     " does not support checkpointing");
      }

      Status RestoreInternal(IteratorContext* ctx,
                             IteratorStateReader* reader) override {
        return errors::Unimplemented(dataset()->DebugString(),
                                     " does not support checkpointing");
      }

     private:
      mutex mu_;
      std::unique_ptr<IteratorBase> input_impl_ GUARDED_BY(mu_);
    };

    const DatasetBase* const input_;
    const Tensor resource_handle_;
    StatsAggregatorResource* stats_aggregator_resource_;
  };
};

REGISTER_KERNEL_BUILDER(Name("SetStatsAggregatorDataset").Device(DEVICE_CPU),
                        SetStatsAggregatorDatasetOp);
}  // namespace
}  // namespace data
}  // namespace tensorflow
