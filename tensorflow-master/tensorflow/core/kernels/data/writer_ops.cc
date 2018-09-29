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

#include "tensorflow/core/framework/op_kernel.h"
#include "tensorflow/core/kernels/data/dataset.h"
#include "tensorflow/core/kernels/data/dataset_utils.h"
#include "tensorflow/core/kernels/ops_util.h"
#include "tensorflow/core/lib/core/threadpool.h"
#include "tensorflow/core/lib/io/record_writer.h"
#include "tensorflow/core/platform/file_system.h"

namespace tensorflow {
namespace data {
namespace {

class ToTFRecordOp : public AsyncOpKernel {
 public:
  explicit ToTFRecordOp(OpKernelConstruction* ctx)
      : AsyncOpKernel(ctx),
        thread_pool_(new thread::ThreadPool(
            ctx->env(), ThreadOptions(),
            strings::StrCat("to_tf_record__op_", SanitizeThreadSuffix(name())),
            1 /* num_threads */, false /* low_latency_hint */)) {}

  template <typename T>
  Status ParseScalarArgument(OpKernelContext* ctx,
                             const StringPiece& argument_name, T* output) {
    const Tensor* argument_t;
    TF_RETURN_IF_ERROR(ctx->input(argument_name, &argument_t));
    if (!TensorShapeUtils::IsScalar(argument_t->shape())) {
      return errors::InvalidArgument(argument_name, " must be a scalar");
    }
    *output = argument_t->scalar<T>()();
    return Status::OK();
  }

  void ComputeAsync(OpKernelContext* ctx, DoneCallback done) override {
    // The call to `iterator->GetNext()` may block and depend on an
    // inter-op thread pool thread, so we issue the call from the
    // owned thread pool.
    thread_pool_->Schedule([this, ctx, done]() {
      string filename;
      OP_REQUIRES_OK_ASYNC(
          ctx, ParseScalarArgument<string>(ctx, "filename", &filename), done);
      string compression_type;
      OP_REQUIRES_OK_ASYNC(ctx,
                           ParseScalarArgument<string>(ctx, "compression_type",
                                                       &compression_type),
                           done);
      std::unique_ptr<WritableFile> file;
      OP_REQUIRES_OK_ASYNC(ctx, ctx->env()->NewWritableFile(filename, &file),
                           done);
      std::unique_ptr<io::RecordWriter> writer;
      writer.reset(new io::RecordWriter(
          file.get(), io::RecordWriterOptions::CreateRecordWriterOptions(
                          compression_type)));

      DatasetBase* dataset;
      OP_REQUIRES_OK_ASYNC(
          ctx, GetDatasetFromVariantTensor(ctx->input(0), &dataset), done);
      std::unique_ptr<IteratorBase> iterator;
      OP_REQUIRES_OK_ASYNC(
          ctx,
          dataset->MakeIterator(IteratorContext(ctx), "ToTFRecordOpIterator",
                                &iterator),
          done);

      std::vector<Tensor> components;
      components.reserve(dataset->output_dtypes().size());
      bool end_of_sequence;
      do {
        OP_REQUIRES_OK_ASYNC(ctx,
                             iterator->GetNext(IteratorContext(ctx),
                                               &components, &end_of_sequence),
                             done);

        if (!end_of_sequence) {
          OP_REQUIRES_OK_ASYNC(
              ctx, writer->WriteRecord(components[0].scalar<string>()()), done);
        }
        components.clear();
      } while (!end_of_sequence);
      done();
    });
  }

 private:
  std::unique_ptr<thread::ThreadPool> thread_pool_;
};

REGISTER_KERNEL_BUILDER(Name("DatasetToTFRecord").Device(DEVICE_CPU),
                        ToTFRecordOp);

}  // namespace
}  // namespace data
}  // namespace tensorflow
