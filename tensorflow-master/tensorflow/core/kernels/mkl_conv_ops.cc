/* Copyright 2015 The TensorFlow Authors. All Rights Reserved.

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

// See docs in ../ops/nn_ops.cc.
#ifdef INTEL_MKL

#include <string.h>
#include <map>
#include <vector>
#include <memory>

#include "tensorflow/core/framework/numeric_op.h"
#include "tensorflow/core/framework/op_kernel.h"
#include "tensorflow/core/framework/register_types.h"
#include "tensorflow/core/framework/tensor.h"
#include "tensorflow/core/framework/tensor_shape.h"
#include "tensorflow/core/framework/tensor_slice.h"
#include "tensorflow/core/kernels/bounds_check.h"
#include "tensorflow/core/kernels/mkl_conv_ops.h"
#include "tensorflow/core/kernels/ops_util.h"
#include "tensorflow/core/lib/core/errors.h"
#include "tensorflow/core/lib/gtl/array_slice.h"
#include "tensorflow/core/lib/strings/numbers.h"
#include "tensorflow/core/lib/strings/str_util.h"
#include "tensorflow/core/lib/strings/strcat.h"
#include "tensorflow/core/platform/logging.h"
#include "tensorflow/core/platform/macros.h"
#include "tensorflow/core/util/padding.h"
#include "tensorflow/core/util/tensor_format.h"

#include "tensorflow/core/util/mkl_util.h"

#ifndef INTEL_MKL_ML_ONLY
#include "mkldnn.hpp"

using mkldnn::prop_kind;
using mkldnn::stream;
using mkldnn::convolution_forward;
using mkldnn::convolution_direct;

#else
#include "mkl_dnn.h"
#include "mkl_dnn_types.h"
#endif

namespace tensorflow {

#ifndef INTEL_MKL_ML_ONLY

// This structure aggregates multiple inputs to Conv2DFwd* methods.
struct MklConvFwdParams {
  memory::dims src_dims;
  memory::dims filter_dims;
  memory::dims bias_dims;
  memory::dims dst_dims;
  memory::dims strides;
  memory::dims dilations;
  memory::dims padding_left;
  memory::dims padding_right;

  MklConvFwdParams(memory::dims src_dims, memory::dims filter_dims,
                   memory::dims bias_dims, memory::dims dst_dims,
                   memory::dims strides, memory::dims dilations,
                   memory::dims padding_left, memory::dims padding_right)
      : src_dims(src_dims),
        filter_dims(filter_dims),
        bias_dims(bias_dims),
        dst_dims(dst_dims),
        strides(strides),
        dilations(dilations),
        padding_left(padding_left),
        padding_right(padding_right) {}
};

template <typename T>
class MklConvFwdPrimitive : public MklPrimitive {
 public:
  explicit MklConvFwdPrimitive(const MklConvFwdParams& convFwdDims)
      : cpu_engine_(engine::cpu, 0) {
    context_.fwd_stream.reset(new stream(stream::kind::eager));
    // create conv primitive
    if (context_.conv_fwd == nullptr) {
      Setup(convFwdDims);
    }
  }

  ~MklConvFwdPrimitive() {}

  // Convolution forward execute with bias
  //   src_data:    input data buffer of src
  //   filter_data: input data buffer of filter (weights)
  //   bias_data:   input data buffer of bias
  //   dst_data:    output data buffer of dst
  void Execute(const T* src_data, const T* filter_data, const T* bias_data,
               const T* dst_data) {
    context_.src_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(src_data)));
    context_.filter_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(filter_data)));
    context_.bias_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(bias_data)));
    context_.dst_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(dst_data)));
    context_.fwd_stream->submit(context_.fwd_primitives);

    // after exec, set data handle back
    context_.src_mem->set_data_handle(DummyData);
    context_.filter_mem->set_data_handle(DummyData);
    context_.bias_mem->set_data_handle(DummyData);
    context_.dst_mem->set_data_handle(DummyData);

    return;
  }

  // Convolution forward execute without bias
  //   src_data:    input data buffer of src
  //   filter_data: input data buffer of filter (weights)
  //   dst_data:    output data buffer of dst
  void Execute(const T* src_data, const T* filter_data, const T* dst_data) {
    context_.src_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(src_data)));
    context_.filter_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(filter_data)));
    context_.dst_mem->set_data_handle(
        static_cast<void*>(const_cast<T*>(dst_data)));
    context_.fwd_stream->submit(context_.fwd_primitives);

    // after execution, set data handle back
    context_.src_mem->set_data_handle(DummyData);
    context_.filter_mem->set_data_handle(DummyData);
    context_.dst_mem->set_data_handle(DummyData);
  }

  memory::format GetSrcMemoryFormat() const { return context_.src_fmt; }

  memory::format GetFilterMemoryFormat() const { return context_.filter_fmt; }

  std::shared_ptr<mkldnn::convolution_forward::primitive_desc>
  GetPrimitiveDesc() const {
    return context_.fwd_pd;
  }

 private:
  // Primitive reuse context for Conv2D Fwd op
  struct ConvFwdContext {
    // expected memory format for this primitive instance
    memory::format src_fmt;
    memory::format filter_fmt;

    // MKLDNN memory
    std::shared_ptr<mkldnn::memory> src_mem;
    std::shared_ptr<mkldnn::memory> filter_mem;
    std::shared_ptr<mkldnn::memory> bias_mem;
    std::shared_ptr<mkldnn::memory> dst_mem;

    // desc & prmitive desc
    std::shared_ptr<mkldnn::convolution_forward::desc> fwd_desc;

    // memory desc
    std::shared_ptr<mkldnn::memory::desc> src_md;
    std::shared_ptr<mkldnn::memory::desc> filter_md;
    std::shared_ptr<mkldnn::memory::desc> bias_md;
    std::shared_ptr<mkldnn::memory::desc> dst_md;

    // convolution primitive
    std::shared_ptr<mkldnn::convolution_forward::primitive_desc> fwd_pd;
    std::shared_ptr<mkldnn::primitive> conv_fwd;

    std::shared_ptr<mkldnn::stream> fwd_stream;
    std::vector<mkldnn::primitive> fwd_primitives;

    ConvFwdContext()
        : src_fmt(memory::format::any),
          filter_fmt(memory::format::any),
          src_mem(nullptr),
          filter_mem(nullptr),
          bias_mem(nullptr),
          dst_mem(nullptr),
          fwd_desc(nullptr),
          src_md(nullptr),
          filter_md(nullptr),
          bias_md(nullptr),
          fwd_pd(nullptr),
          conv_fwd(nullptr),
          fwd_stream(nullptr) {}
  };

  void Setup(const MklConvFwdParams& convFwdDims) {
    // create memory descriptors for convolution data w/ no specified format
    context_.src_md.reset(new memory::desc(
        {convFwdDims.src_dims}, MklDnnType<T>(), memory::format::any));

    context_.filter_md.reset(new memory::desc(
        {convFwdDims.filter_dims}, MklDnnType<T>(), memory::format::any));

    context_.dst_md.reset(new memory::desc(
        {convFwdDims.dst_dims}, MklDnnType<T>(), memory::format::any));

    if (!convFwdDims.bias_dims.empty())
      context_.bias_md.reset(new memory::desc(
          {convFwdDims.bias_dims}, MklDnnType<T>(), memory::format::any));

    // create a convolution
    if (!convFwdDims.bias_dims.empty()) {
      context_.fwd_desc.reset(new convolution_forward::desc(
          prop_kind::forward, convolution_direct, *context_.src_md,
          *context_.filter_md, *context_.bias_md, *context_.dst_md,
          convFwdDims.strides, convFwdDims.dilations, convFwdDims.padding_left,
          convFwdDims.padding_right, padding_kind::zero));
    } else {
      context_.fwd_desc.reset(new convolution_forward::desc(
          prop_kind::forward, convolution_direct, *context_.src_md,
          *context_.filter_md, *context_.dst_md, convFwdDims.strides,
          convFwdDims.dilations, convFwdDims.padding_left,
          convFwdDims.padding_right, padding_kind::zero));
    }

    context_.fwd_pd.reset(new convolution_forward::primitive_desc(
        *context_.fwd_desc, cpu_engine_));

    // store the expected memory format
    context_.src_fmt = static_cast<mkldnn::memory::format>(
        context_.fwd_pd.get()->src_primitive_desc().desc().data.format);

    context_.filter_fmt = static_cast<mkldnn::memory::format>(
        context_.fwd_pd.get()->weights_primitive_desc().desc().data.format);

    // create memory primitive based on dummy data
    context_.src_mem.reset(
        new memory(context_.fwd_pd.get()->src_primitive_desc(), DummyData));
    context_.filter_mem.reset(
        new memory(context_.fwd_pd.get()->weights_primitive_desc(), DummyData));
    context_.dst_mem.reset(
        new memory(context_.fwd_pd.get()->dst_primitive_desc(), DummyData));

    // create convolution primitive and add it to net
    if (!convFwdDims.bias_dims.empty()) {
      context_.bias_mem.reset(new memory(
          {{{convFwdDims.bias_dims}, MklDnnType<T>(), memory::format::x},
           cpu_engine_},
          DummyData));
      context_.conv_fwd.reset(new convolution_forward(
          *context_.fwd_pd, *context_.src_mem, *context_.filter_mem,
          *context_.bias_mem, *context_.dst_mem));
    } else {
      context_.conv_fwd.reset(
          new convolution_forward(*context_.fwd_pd, *context_.src_mem,
                                  *context_.filter_mem, *context_.dst_mem));
    }

    context_.fwd_primitives.push_back(*context_.conv_fwd);
    return;
  }

  struct ConvFwdContext context_;
  engine cpu_engine_;
};

template <typename T>
class MklConvFwdPrimitiveFactory : public MklPrimitiveFactory<T> {
 public:
  static MklConvFwdPrimitive<T>* Get(const MklConvFwdParams& convFwdDims,
                                     bool do_not_cache) {
    MklConvFwdPrimitive<T>* conv_fwd = nullptr;

    if (do_not_cache) { /* Always create new primitive */
      conv_fwd = new MklConvFwdPrimitive<T>(convFwdDims);
    } else {
      // try to find a suitable one in pool
      conv_fwd = dynamic_cast<MklConvFwdPrimitive<T>*>(
          MklConvFwdPrimitiveFactory<T>::GetInstance().GetConvFwd(convFwdDims));
      if (conv_fwd == nullptr) {
        conv_fwd = new MklConvFwdPrimitive<T>(convFwdDims);
        MklConvFwdPrimitiveFactory<T>::GetInstance().SetConvFwd(convFwdDims,
                                                                conv_fwd);
      }
    }

    return conv_fwd;
  }

 private:
  MklConvFwdPrimitiveFactory() {}
  ~MklConvFwdPrimitiveFactory() {}

  static const int kDilationH = 0, kDilationW = 1;

  static MklConvFwdPrimitiveFactory& GetInstance() {
    static MklConvFwdPrimitiveFactory instance_;
    return instance_;
  }

  static string CreateKey(const MklConvFwdParams& convFwdDims) {
    string prefix = "conv_fwd_";
    FactoryKeyCreator key_creator;
    key_creator.AddAsKey(prefix);
    key_creator.AddAsKey(convFwdDims.src_dims);
    key_creator.AddAsKey(convFwdDims.filter_dims);
    key_creator.AddAsKey(convFwdDims.bias_dims);
    key_creator.AddAsKey(convFwdDims.dst_dims);
    key_creator.AddAsKey(convFwdDims.strides);
    key_creator.AddAsKey(convFwdDims.dilations);
    key_creator.AddAsKey(convFwdDims.padding_left);
    key_creator.AddAsKey(convFwdDims.padding_right);
    return key_creator.GetKey();
  }

  MklPrimitive* GetConvFwd(const MklConvFwdParams& convFwdDims) {
    string key = CreateKey(convFwdDims);
    return this->GetOp(key);
  }

  void SetConvFwd(const MklConvFwdParams& convFwdDims, MklPrimitive* op) {
    string key = CreateKey(convFwdDims);
    this->SetOp(key, op);
  }
};

#endif

typedef Eigen::ThreadPoolDevice CPUDevice;

// For now, MKL-ML is default. So making MKL-DNN not a default choice.
#ifdef INTEL_MKL_ML_ONLY
template <typename Device, typename T, bool biasEnabled>
class MklConvOp : public OpKernel {
 public:
  ~MklConvOp() {}

  explicit MklConvOp(OpKernelConstruction* context) : OpKernel(context) {
    OP_REQUIRES_OK(context, context->GetAttr("strides", &strides_));
    string data_format;
    OP_REQUIRES_OK(context, context->GetAttr("data_format", &data_format));
    OP_REQUIRES(context, FormatFromString(data_format, &data_format_),
                errors::InvalidArgument("Invalid data format"));
    OP_REQUIRES(context, strides_.size() == 4,
                errors::InvalidArgument("Sliding window strides field must "
                                        "specify 4 dimensions"));

    const int64 stride_n = GetTensorDim(strides_, data_format_, 'N');
    const int64 stride_c = GetTensorDim(strides_, data_format_, 'C');
    OP_REQUIRES(
        context, stride_n == 1 && stride_c == 1,
        errors::InvalidArgument("Current implementation does not yet support "
                                "strides in the batch and depth dimensions."));
    OP_REQUIRES_OK(context, context->GetAttr("padding", &padding_));
  }

  void Compute(OpKernelContext* context) override {
    MklConv2DOpContext mkl_context;
    const Tensor& input = MklGetInput(context, 0);
    GetMklShape(context, 0, &(mkl_context.input_shape));
    bool input_in_mkl_format = mkl_context.input_shape.IsMklTensor();

    const Tensor& filter = MklGetInput(context, 1);
    MklShape mkl_filter_shape;
    GetMklShape(context, 1, &mkl_filter_shape);
    CHECK(!mkl_filter_shape.IsMklTensor())
        << "Conv filter should not be in MKL Layout";

    if (biasEnabled) {
      const Tensor& bias = MklGetInput(context, 2);
      OP_REQUIRES(context, bias.dims() == 1,
                  errors::InvalidArgument("bias must be 1-dimensional: ",
                                          bias.shape().DebugString()));
    }

    if (!input_in_mkl_format) {
      OP_REQUIRES(context, input.dims() == 4,
                  errors::InvalidArgument("input must be 4-dimensional",
                                          input.shape().DebugString()));
    }

    OP_REQUIRES(context, filter.dims() == 4,
                errors::InvalidArgument("filter must be 4-dimensional: ",
                                        filter.shape().DebugString()));

    for (int i = 0; i < 3; i++) {
      OP_REQUIRES(
          context,
          FastBoundsCheck(filter.dim_size(i), std::numeric_limits<int>::max()),
          errors::InvalidArgument("filter too large"));
    }

    const int64 input_depth =
        input_in_mkl_format ? GetMklTensorDim(mkl_context.input_shape, 'C')
                            : GetTensorDim(input, data_format_, 'C');
    OP_REQUIRES(context, input_depth == filter.dim_size(2),
                errors::InvalidArgument(
                    "input and filter must have the same depth: ", input_depth,
                    " vs ", filter.dim_size(2)));
    // The last dimension for filter is out_depth.
    const int out_depth = static_cast<int>(filter.dim_size(3));

    // The second dimension for input is rows/height.
    // The first dimension for filter is rows/height.
    const int64 input_rows_raw =
        input_in_mkl_format ? GetMklTensorDim(mkl_context.input_shape, 'H')
                            : GetTensorDim(input, data_format_, 'H');
    OP_REQUIRES(
        context,
        FastBoundsCheck(input_rows_raw, std::numeric_limits<int>::max()),
        errors::InvalidArgument("Input rows too large"));
    const int input_rows = static_cast<int>(input_rows_raw);
    const int filter_rows = static_cast<int>(filter.dim_size(0));

    // The third dimension for input is columns/width.
    // The second dimension for filter is columns/width.
    const int64 input_cols_raw =
        input_in_mkl_format ? GetMklTensorDim(mkl_context.input_shape, 'W')
                            : GetTensorDim(input, data_format_, 'W');
    OP_REQUIRES(
        context,
        FastBoundsCheck(input_cols_raw, std::numeric_limits<int>::max()),
        errors::InvalidArgument("Input cols too large"));
    const int input_cols = static_cast<int>(input_cols_raw);
    const int filter_cols = static_cast<int>(filter.dim_size(1));

    // The first dimension for input is batch.
    const int64 input_batch_raw =
        input_in_mkl_format ? GetMklTensorDim(mkl_context.input_shape, 'N')
                            : GetTensorDim(input, data_format_, 'N');
    OP_REQUIRES(
        context,
        FastBoundsCheck(input_batch_raw, std::numeric_limits<int>::max()),
        errors::InvalidArgument("batch is too large"));
    const int batch = static_cast<int>(input_batch_raw);

    // For now we take the stride from the second and third dimensions only (we
    // do not support striding on the batch or depth dimension).
    const int stride_rows = GetTensorDim(strides_, data_format_, 'H');
    const int stride_cols = GetTensorDim(strides_, data_format_, 'W');

    int64 out_rows = 0, out_cols = 0, pad_rows = 0, pad_cols = 0;
    OP_REQUIRES_OK(context,
                   GetWindowedOutputSize(input_rows, filter_rows, stride_rows,
                                         padding_, &out_rows, &pad_rows));
    OP_REQUIRES_OK(context,
                   GetWindowedOutputSize(input_cols, filter_cols, stride_cols,
                                         padding_, &out_cols, &pad_cols));
    TensorShape out_shape =
        ShapeFromFormat(data_format_, batch, out_rows, out_cols, out_depth);

    // Output tensor is of the following dimensions:
    // [ in_batch, out_rows, out_cols, out_depth ]
    Tensor* output = nullptr;

    // If there is nothing to compute, return.
    if (out_shape.num_elements() == 0) {
      // Nothing to do, allocate output tensor and return
      MklShape mkl_output_mkl_shape;
      mkl_output_mkl_shape.SetMklTensor(false);
      AllocateOutputSetMklShape(context, 0, &output, input.shape(),
                                mkl_output_mkl_shape);
      return;
    }

    if (batch == 0) {
      // Nothing to do, allocate output tensor and return
      MklShape mkl_output_mkl_shape;
      mkl_output_mkl_shape.SetMklTensor(false);
      AllocateOutputSetMklShape(context, 0, &output, input.shape(),
                                mkl_output_mkl_shape);
      return;
    }

    // Create MKL convolution primitives
    mkl_context.in_dims = input_in_mkl_format
                              ? mkl_context.input_shape.GetDimension()
                              : input.dims();
    mkl_context.filter_dims = filter.dims();

    mkl_context.in_sizes[MklDims::W] = static_cast<size_t>(input_cols);
    mkl_context.in_sizes[MklDims::H] = static_cast<size_t>(input_rows);
    mkl_context.in_sizes[MklDims::C] = static_cast<size_t>(input_depth);
    mkl_context.in_sizes[MklDims::N] = static_cast<size_t>(batch);

    mkl_context.out_sizes[MklDims::W] = static_cast<size_t>(out_cols);
    mkl_context.out_sizes[MklDims::H] = static_cast<size_t>(out_rows);
    mkl_context.out_sizes[MklDims::C] = static_cast<size_t>(out_depth);
    mkl_context.out_sizes[MklDims::N] = static_cast<size_t>(batch);

    mkl_context.input_offset[0] = static_cast<int>(-pad_cols);
    mkl_context.input_offset[1] = static_cast<int>(-pad_rows);

    mkl_context.conv_stride[0] = static_cast<size_t>(stride_cols);
    mkl_context.conv_stride[1] = static_cast<size_t>(stride_rows);

    GetStridesFromSizes(data_format_, mkl_context.out_strides,
                        mkl_context.out_sizes);
    GetStridesFromSizes(data_format_, mkl_context.in_strides,
                        mkl_context.in_sizes);

    // TF filter dimension order (out_depth, in_depth, cols, rows) ->
    // MKL filter dimension order (out_depth, in_depth, rows, cols)
    mkl_context.filter_sizes[0] = filter.dim_size(1);  // cols
    mkl_context.filter_sizes[1] = filter.dim_size(0);  // rows
    mkl_context.filter_sizes[2] = filter.dim_size(2);  // in_depth
    mkl_context.filter_sizes[3] = filter.dim_size(3);  // out_depth

    // TF filter layout - (rows, cols, in_depth, out_depth)
    mkl_context.filter_strides[0] =
        filter.dim_size(2) * filter.dim_size(3);  // cols
    mkl_context.filter_strides[1] =
        filter.dim_size(1) * filter.dim_size(2) * filter.dim_size(3);  // rows
    mkl_context.filter_strides[2] = filter.dim_size(3);  // in_depth
    mkl_context.filter_strides[3] = 1;                   // out_depth

    if (biasEnabled) {
      const Tensor& bias = MklGetInput(context, 2);
      mkl_context.bias_sizes[0] = {static_cast<size_t>(bias.dim_size(0))};
      mkl_context.bias_strides[0] = {1};
    }

    // Create Convolution Primitive
    if (biasEnabled) {
      CHECK_EQ(
          dnnConvolutionCreateForwardBias_F32(
              &mkl_context.prim_fwd, nullptr, dnnAlgorithmConvolutionDirect,
              mkl_context.in_dims, mkl_context.in_sizes, mkl_context.out_sizes,
              mkl_context.filter_sizes, mkl_context.conv_stride,
              mkl_context.input_offset, dnnBorderZeros),
          E_SUCCESS);
    } else {
      CHECK_EQ(
          dnnConvolutionCreateForward_F32(
              &mkl_context.prim_fwd, nullptr, dnnAlgorithmConvolutionDirect,
              mkl_context.in_dims, mkl_context.in_sizes, mkl_context.out_sizes,
              mkl_context.filter_sizes, mkl_context.conv_stride,
              mkl_context.input_offset, dnnBorderZeros),
          E_SUCCESS);
    }

    TensorShape mkl_output_tf_shape;
    MklShape mkl_output_mkl_shape;
    mkl_output_mkl_shape.SetMklTensor(true);
    mkl_output_mkl_shape.SetMklLayout(mkl_context.prim_fwd, dnnResourceDst);
    mkl_output_mkl_shape.SetTfLayout(mkl_context.in_dims, mkl_context.out_sizes,
                                     mkl_context.out_strides);
    // MKL might change the dimension ordering
    // Create mapping to recover the original TF dimension order
    mkl_output_mkl_shape.SetTfDimOrder(mkl_context.in_dims, data_format_);

    mkl_output_tf_shape.AddDim(
        dnnLayoutGetMemorySize_F32(
            static_cast<dnnLayout_t>(mkl_output_mkl_shape.GetMklLayout())) /
        sizeof(T));
    AllocateOutputSetMklShape(context, 0, &output, mkl_output_tf_shape,
                              mkl_output_mkl_shape);
    // Filter output to be used in the backprop_input
    TensorShape mkl_filter_output_tf_shape;
    MklShape mkl_filter_output_mkl_shape;
    mkl_filter_output_mkl_shape.SetMklTensor(true);
    mkl_filter_output_mkl_shape.SetMklLayout(mkl_context.prim_fwd,
                                             dnnResourceFilter);

    size_t filter_sizes[4] = {static_cast<size_t>(filter.dim_size(0)),
                              static_cast<size_t>(filter.dim_size(1)),
                              static_cast<size_t>(filter.dim_size(2)),
                              static_cast<size_t>(filter.dim_size(3))};
    mkl_filter_output_mkl_shape.SetTfLayout(filter.dims(), filter_sizes,
                                            mkl_context.filter_strides);

    mkl_filter_output_mkl_shape.SetTfDimOrder(mkl_context.filter_dims,
                                              data_format_);
    mkl_filter_output_tf_shape.AddDim(
        dnnLayoutGetMemorySize_F32(static_cast<dnnLayout_t>(
            mkl_filter_output_mkl_shape.GetMklLayout())) /
        sizeof(T));
    AllocateOutputSetMklShape(context, 1, &mkl_context.output_filter,
                              mkl_filter_output_tf_shape,
                              mkl_filter_output_mkl_shape);

    mkl_context.conv_res[dnnResourceDst] =
        static_cast<void*>(output->flat<T>().data());

    mkl_context.MklCreateInputLayouts(context);

    // Temp tensor used to allocate tmp buffers
    Tensor mkl_tmp_input_buf_tensor, mkl_tmp_filter_buf_tensor,
        mkl_tmp_bias_buf_tensor;
    mkl_context.MklPrepareConvolutionInputs(context, &mkl_tmp_input_buf_tensor,
                                            &mkl_tmp_filter_buf_tensor,
                                            &mkl_tmp_bias_buf_tensor);

    // Execute convolution
    CHECK_EQ(dnnExecute_F32(mkl_context.prim_fwd, mkl_context.conv_res),
             E_SUCCESS);

    mkl_context.MklCleanup();
  }

 private:
  typedef struct {
    int in_dims;
    size_t in_sizes[4];
    size_t in_strides[4];
    size_t out_sizes[4];
    size_t out_strides[4];
    int filter_dims;
    size_t filter_sizes[4];
    size_t filter_strides[4];
    size_t bias_sizes[1];
    size_t bias_strides[1];
    int input_offset[2];
    size_t conv_stride[2];
    MklShape input_shape;
    dnnPrimitive_t prim_fwd;
    void* conv_res[dnnResourceNumber];
    dnnLayout_t lt_filter, lt_bias, lt_input;
    Tensor* output_filter = nullptr;

    // Create MKL dnnLayout_t objects for tensors coming into the layer
    void MklCreateInputLayouts(OpKernelContext* context) {
      bool input_in_mkl_format = input_shape.IsMklTensor();
      if (input_in_mkl_format) {
        lt_input = static_cast<dnnLayout_t>(input_shape.GetCurLayout());
      } else {
        CHECK_EQ(dnnLayoutCreate_F32(&lt_input, in_dims, in_sizes, in_strides),
                 E_SUCCESS);
      }

      CHECK_EQ(dnnLayoutCreate_F32(&lt_filter, filter_dims, filter_sizes,
                                   filter_strides),
               E_SUCCESS);

      if (biasEnabled) {
        CHECK_EQ(dnnLayoutCreate_F32(&lt_bias, 1, bias_sizes, bias_strides),
                 E_SUCCESS);
      }
    }

    // Compare incoming tensor layouts with MKL preferred layouts and convert
    // data to the preferred layout if necessary
    void MklPrepareConvolutionInputs(OpKernelContext* context,
                                     Tensor* mkl_tmp_input_buf_tensor,
                                     Tensor* mkl_tmp_filter_buf_tensor,
                                     Tensor* mkl_tmp_bias_buf_tensor) {
      bool mkl_convert_input, mkl_convert_filter, mkl_convert_bias;
      dnnPrimitive_t mkl_prim_convert_filter, mkl_prim_convert_bias,
          mkl_prim_convert_input;
      dnnLayout_t mkl_lt_internal_filter, mkl_lt_internal_bias,
          mkl_lt_internal_input;
      void *mkl_buf_convert_input, *mkl_buf_convert_filter,
          *mkl_buf_convert_bias;
      mkl_prim_convert_filter = nullptr;
      mkl_prim_convert_bias = nullptr;
      mkl_prim_convert_input = nullptr;
      mkl_lt_internal_filter = nullptr;
      mkl_lt_internal_bias = nullptr;
      mkl_lt_internal_input = nullptr;
      mkl_buf_convert_input = nullptr;
      mkl_buf_convert_filter = nullptr;
      mkl_buf_convert_bias = nullptr;

      // Compare with internal layouts and convert if needed
      const Tensor& input = MklGetInput(context, 0);
      void* mkl_buf_input =
          const_cast<void*>(static_cast<const void*>(input.flat<T>().data()));
      CHECK_EQ(dnnLayoutCreateFromPrimitive_F32(&mkl_lt_internal_input,
                                                prim_fwd, dnnResourceSrc),
               E_SUCCESS);
      mkl_convert_input =
          !dnnLayoutCompare_F32(mkl_lt_internal_input, lt_input);
      if (mkl_convert_input) {
        CHECK_EQ(dnnConversionCreate_F32(&mkl_prim_convert_input, lt_input,
                                         mkl_lt_internal_input),
                 E_SUCCESS);
        AllocTmpBuffer(context, mkl_tmp_input_buf_tensor, mkl_lt_internal_input,
                       &mkl_buf_convert_input);
        CHECK_EQ(dnnConversionExecute_F32(mkl_prim_convert_input, mkl_buf_input,
                                          mkl_buf_convert_input),
                 E_SUCCESS);
        dnnDelete_F32(mkl_prim_convert_input);
      }
      dnnLayoutDelete_F32(mkl_lt_internal_input);

      conv_res[dnnResourceSrc] =
          (mkl_convert_input) ? mkl_buf_convert_input : mkl_buf_input;

      const Tensor& filter = MklGetInput(context, 1);
      void* mkl_buf_filter =
          const_cast<void*>(static_cast<const void*>(filter.flat<T>().data()));
      CHECK_EQ(dnnLayoutCreateFromPrimitive_F32(&mkl_lt_internal_filter,
                                                prim_fwd, dnnResourceFilter),
               E_SUCCESS);
      mkl_convert_filter =
          !dnnLayoutCompare_F32(mkl_lt_internal_filter, lt_filter);
      if (mkl_convert_filter) {
        CHECK_EQ(dnnConversionCreate_F32(&mkl_prim_convert_filter, lt_filter,
                                         mkl_lt_internal_filter),
                 E_SUCCESS);

        mkl_buf_convert_filter = const_cast<void*>(
            static_cast<const void*>(output_filter->flat<T>().data()));

        CHECK_EQ(
            dnnConversionExecute_F32(mkl_prim_convert_filter, mkl_buf_filter,
                                     mkl_buf_convert_filter),
            E_SUCCESS);
        dnnDelete_F32(mkl_prim_convert_filter);
      }
      dnnLayoutDelete_F32(mkl_lt_internal_filter);

      conv_res[dnnResourceFilter] =
          (mkl_convert_filter) ? mkl_buf_convert_filter : mkl_buf_filter;

      if (biasEnabled) {
        const Tensor& bias = MklGetInput(context, 2);
        void* mkl_buf_bias =
            const_cast<void*>(static_cast<const void*>(bias.flat<T>().data()));
        CHECK_EQ(dnnLayoutCreateFromPrimitive_F32(&mkl_lt_internal_bias,
                                                  prim_fwd, dnnResourceBias),
                 E_SUCCESS);
        mkl_convert_bias = !dnnLayoutCompare_F32(mkl_lt_internal_bias, lt_bias);
        if (mkl_convert_bias) {
          CHECK_EQ(dnnConversionCreate_F32(&mkl_prim_convert_bias, lt_bias,
                                           mkl_lt_internal_bias),
                   E_SUCCESS);
          AllocTmpBuffer(context, mkl_tmp_bias_buf_tensor, mkl_lt_internal_bias,
                         &mkl_buf_convert_bias);
          CHECK_EQ(dnnConversionExecute_F32(mkl_prim_convert_bias, mkl_buf_bias,
                                            mkl_buf_convert_bias),
                   E_SUCCESS);
          dnnDelete_F32(mkl_prim_convert_bias);
        }
        dnnLayoutDelete_F32(mkl_lt_internal_bias);

        conv_res[dnnResourceBias] =
            (mkl_convert_bias) ? mkl_buf_convert_bias : mkl_buf_bias;
      }
    }

    void MklCleanup() {
      bool input_in_mkl_format = input_shape.IsMklTensor();
      dnnDelete_F32(prim_fwd);
      if (!input_in_mkl_format) dnnLayoutDelete_F32(lt_input);
      dnnLayoutDelete_F32(lt_filter);
      if (biasEnabled) dnnLayoutDelete_F32(lt_bias);
    }
  } MklConv2DOpContext;

  std::vector<int32> strides_;
  Padding padding_;
  TensorFormat data_format_;
};

#else

// Base class for convolution forward operations
template <typename Device, typename T, bool biasEnabled>
class MklConvOp : public OpKernel {
 public:
  ~MklConvOp() {}

  explicit MklConvOp(OpKernelConstruction* context) : OpKernel(context) {
    OP_REQUIRES_OK(context, context->GetAttr("dilations", &dilations_));
    OP_REQUIRES_OK(context, context->GetAttr("strides", &strides_));
    string data_format;
    OP_REQUIRES_OK(context, context->GetAttr("data_format", &data_format));
    OP_REQUIRES(context, FormatFromString(data_format, &data_format_),
                errors::InvalidArgument("Invalid data format"));
    OP_REQUIRES(context, (strides_.size() == 4 || strides_.size() == 5),
                errors::InvalidArgument("Sliding window strides field must "
                                        "specify 4 or 5 dimensions"));

    const int64 stride_n = GetTensorDim(strides_, data_format_, 'N');
    const int64 stride_c = GetTensorDim(strides_, data_format_, 'C');
    OP_REQUIRES(
        context, stride_n == 1 && stride_c == 1,
        errors::InvalidArgument("Current implementation does not yet support "
                                "strides in the batch and depth dimensions."));
    OP_REQUIRES_OK(context, context->GetAttr("padding", &padding_));

    if (strides_.size() == 4) {
      OP_REQUIRES(context, dilations_.size() == 4,
                  errors::InvalidArgument("Sliding window dilations field must "
                                          "specify 4 dimensions"));
      const int64 dilation_n = GetTensorDim(dilations_, data_format_, 'N');
      const int64 dilation_c = GetTensorDim(dilations_, data_format_, 'C');
      const int64 dilation_h = GetTensorDim(dilations_, data_format_, 'H');
      const int64 dilation_w = GetTensorDim(dilations_, data_format_, 'W');
      OP_REQUIRES(context, dilation_n == 1 && dilation_c == 1,
                  errors::InvalidArgument(
                      "Current implementation does not yet support "
                      "dilations in the batch and depth dimensions."));
      OP_REQUIRES(
          context, dilation_h > 0 && dilation_w > 0,
          errors::InvalidArgument("Dilated rates should be larger than 0."));
    } else if (strides_.size() == 5) {
      OP_REQUIRES(context, dilations_.size() == 5,
                  errors::InvalidArgument("Dilation rates field must "
                                          "specify 5 dimensions"));
      OP_REQUIRES(context,
                  (GetTensorDim(dilations_, data_format_, 'N') == 1 &&
                   GetTensorDim(dilations_, data_format_, 'C') == 1),
                  errors::InvalidArgument(
                      "Current implementation does not yet support "
                      "dilations rates in the batch and depth dimensions."));
      OP_REQUIRES(
          context,
          (GetTensorDim(dilations_, data_format_, '0') > 0 &&
           GetTensorDim(dilations_, data_format_, '1') > 0 &&
           GetTensorDim(dilations_, data_format_, '2') > 0),
          errors::InvalidArgument("Dilated rates should be larger than 0."));
    }
  }

  void Compute(OpKernelContext* context) override {
    try {
      // Input tensors
      const Tensor& src_tensor = MklGetInput(context, kInputIndex_Src);
      const Tensor& filter_tensor = MklGetInput(context, kInputIndex_Filter);

      MklDnnShape src_mkl_shape, filter_mkl_shape;
      GetMklShape(context, kInputIndex_Src, &src_mkl_shape);
      GetMklShape(context, kInputIndex_Filter, &filter_mkl_shape);
      OP_REQUIRES(context, filter_mkl_shape.IsMklTensor() == false,
            errors::InvalidArgument("Filter should not be in "
            "Mkl Layout"));

      MklDnnData<T> src(&cpu_engine);
      MklDnnData<T> filter(&cpu_engine);

      memory::dims src_dims, filter_dims, padding_left, padding_right,
                   dilations, strides;
      memory::dims dst_dims_tf_order, dst_dims_mkl_order;

      // Get shapes of input tensors in MKL-DNN order
      MklDnnConvUtil conv_utl(context, strides_, padding_, data_format_,
                             dilations_);
      auto src_tf_shape = GetTfShape(context, kInputIndex_Src);
      auto filter_tf_shape = GetTfShape(context, kInputIndex_Filter);
      conv_utl.GetConvFwdSizesInMklOrder(
          src_tf_shape, filter_tf_shape, &src_dims, &filter_dims,
          &strides, &dilations, &dst_dims_tf_order, &dst_dims_mkl_order,
          &padding_left, &padding_right);
      if (!context->status().ok()) return;

      // Check for corner case - if there is nothing to compute, return.
      TensorShape dst_tf_shape = MklDnnDimsToTFShape(dst_dims_tf_order);

      // Corner cases: output with 0 elements and 0 batch size.
      Tensor* dst_tensor = nullptr;
      if (dst_tf_shape.num_elements() == 0 ||
          dst_dims_tf_order[0] == 0) {
        MklDnnShape dst_mkl_shape;
        dst_mkl_shape.SetMklTensor(false);
        AllocateOutputSetMklShape(context, kOutputIndex_Dst,
                    &dst_tensor, src_tf_shape, dst_mkl_shape);

        // MklConv2D/3D also outputs converted filter
        // as 2nd output of Conv2D/3D.
        filter_mkl_shape.SetMklTensor(false);
        Tensor* output_filter_tensor = nullptr;
        AllocateOutputSetMklShape(context, kOutputIndex_Filter,
                                  &output_filter_tensor,
                                  filter_tf_shape, filter_mkl_shape);
        return;
      }

      bool isConv2D = (strides_.size() == 4);

      // Create memory for user data.
      // Describe how the inputs and outputs of Convolution look like. Also
      // specify buffers containing actual input and output data.
      auto tf_fmt = isConv2D ? TFDataFormatToMklDnnDataFormat(data_format_)
                             : TFDataFormatToMklDnn3DDataFormat(data_format_);

      // If input is in MKL layout, then simply grab input layout; otherwise,
      // construct input Tf layout. For TF layout, although input shape
      // (src_dims) required is in MKL-DNN order, the layout is Tensorflow's
      // layout depending on data format:
      //     Conv2D: NHWC or NCHW
      //     Conv3D: NDHWC or NCDHW
      auto src_md = src_mkl_shape.IsMklTensor()
                        ? src_mkl_shape.GetMklLayout()
                        : memory::desc(src_dims, MklDnnType<T>(), tf_fmt);

      // Although filter shape (filter_dims) required is in MKL-DNN order,
      // the layout is Tensorflow's layout (HWIO).
      auto filter_md = filter_mkl_shape.IsMklTensor()  // Should NEVER be true
                           ? filter_mkl_shape.GetMklLayout()
                           : memory::desc(filter_dims, MklDnnType<T>(),
                                          isConv2D ? memory::format::hwio
                                                   : memory::format::dhwio);
      // MKLDNN dilation starts from 0.
      for (int i = 0; i < dilations.size(); i++) dilations[i] -= 1;

      // In some cases, primitve descriptor includes potentialy large buffers,
      // we don't cache those primitves if the env variable
      // TF_MKL_OPTIMIZE_PRIMITIVE_MEMUSE is true. MKL DNN allocates buffers
      // in the following cases
      //   1. Legacy CPU without AVX512/AVX2, or
      //   2. 1x1 convolution with stride != 1
      bool do_not_cache = MklPrimitiveFactory<T>::IsPrimitiveMemOptEnabled() &&
                    (src_dims[MklDnnDims::Dim_N] > kSmallBatchSize) &&
                    (MklPrimitiveFactory<T>::IsLegacyPlatform() ||
                     IsConv1x1StrideNot1(filter_dims, strides));

      // get a conv2d fwd from primitive pool
      MklConvFwdPrimitive<T>* conv_fwd = nullptr;
      if (biasEnabled) {
        memory::dims bias_dims = {};
        conv_utl.GetBiasSizeInMklOrder(kInputIndex_Bias, &bias_dims);
        MklConvFwdParams convFwdDims(src_dims, filter_dims, bias_dims,
                                     dst_dims_mkl_order, strides, dilations,
                                     padding_left, padding_right);
        conv_fwd = MklConvFwdPrimitiveFactory<T>::Get(
            convFwdDims, do_not_cache);
      } else {
        MklConvFwdParams convFwdDims(src_dims, filter_dims, NONE_DIMS,
                                     dst_dims_mkl_order, strides, dilations,
                                     padding_left, padding_right);
        conv_fwd = MklConvFwdPrimitiveFactory<T>::Get(
            convFwdDims, do_not_cache);
      }

      // allocate output tensors output_tensor and filter_out_tensor
      std::shared_ptr<mkldnn::convolution_forward::primitive_desc> conv_fwd_pd =
          conv_fwd->GetPrimitiveDesc();
      AllocateOutputTensor(context, *conv_fwd_pd,
                       dst_dims_mkl_order, tf_fmt, &dst_tensor);
      Tensor* filter_out_tensor = nullptr;
      AllocateFilterOutputTensor(context, *conv_fwd_pd,
                                 TFShapeToMklDnnDims(filter_tf_shape),
                                 &filter_out_tensor);

      T* dst_data = static_cast<T*>(dst_tensor->flat<T>().data());

      // check whether src/filter need reorder
      T *src_data = nullptr;
      if (src_md.data.format != conv_fwd->GetSrcMemoryFormat()) {
        src.SetUsrMem(src_md, &src_tensor);
        src.CheckReorderToOpMem(conv_fwd_pd.get()->src_primitive_desc());
        src_data = static_cast<T*>(src.GetOpMem().get_data_handle());
      } else {
        src_data = static_cast<T*>(const_cast<T*>(src_tensor.flat<T>().data()));
      }
      T* filter_data = nullptr;
      if (filter_md.data.format != conv_fwd->GetFilterMemoryFormat()) {
        filter.SetUsrMem(filter_md, &filter_tensor);
        filter.CheckReorderToOpMem(conv_fwd_pd.get()->weights_primitive_desc(),
                                   filter.GetTensorBuffer(filter_out_tensor));
        filter_data = static_cast<T*>(filter.GetOpMem().get_data_handle());
      } else {
        filter_data =
            static_cast<T*>(const_cast<T*>(filter_tensor.flat<T>().data()));
      }

      // execute convolution
      if (biasEnabled) {
        const Tensor& bias_tensor = MklGetInput(context, kInputIndex_Bias);
        T* bias_data = static_cast<T*>(const_cast<T*>(
            bias_tensor.flat<T>().data()));

        conv_fwd->Execute(src_data, filter_data, bias_data, dst_data);
      } else {
        conv_fwd->Execute(src_data, filter_data, dst_data);
      }

      // delete primitive since it is not cached.
      if (do_not_cache) delete conv_fwd;
    } catch (mkldnn::error &e) {
      string error_msg = tensorflow::strings::StrCat(
          "Status: ", e.status, ", message: ", string(e.message), ", in file ",
          __FILE__, ":", __LINE__);
      OP_REQUIRES_OK(context,
        errors::Aborted("Operation received an exception:", error_msg));
    }
  }

 private:
  std::vector<int32> strides_;
  std::vector<int32> dilations_;
  Padding padding_;
  TensorFormat data_format_;
  const int kInputIndex_Src = 0, kInputIndex_Filter = 1, kInputIndex_Bias = 2;
  const int kOutputIndex_Dst = 0, kOutputIndex_Filter = 1;
  const int kDilationH = 0, kDilationW = 1;
  engine cpu_engine = engine(engine::cpu, 0);

  // Allocate output tensor.
  void AllocateOutputTensor(
      OpKernelContext* context,
      const convolution_forward::primitive_desc& conv_prim_desc,
      const memory::dims& output_dims_mkl_order,
      memory::format output_tf_format, Tensor** output_tensor) {
    CHECK_NOTNULL(output_tensor);
    auto dst_pd = conv_prim_desc.dst_primitive_desc();

    // Allocate shape of Mkl tensor.
    MklDnnShape output_mkl_shape;
    output_mkl_shape.SetMklTensor(true);
    output_mkl_shape.SetMklLayout(&dst_pd);
    output_mkl_shape.SetElemType(MklDnnType<T>());
    output_mkl_shape.SetTfLayout(output_dims_mkl_order.size(),
                                 output_dims_mkl_order, output_tf_format);

    // Allocate shape of TF tensor.
    TensorShape output_tf_shape;
    output_tf_shape.AddDim((dst_pd.get_size() / sizeof(T)));

    AllocateOutputSetMklShape(context, kOutputIndex_Dst, output_tensor,
                              output_tf_shape, output_mkl_shape);
  }

  // Allocate output tensor.
  void AllocateFilterOutputTensor(
      OpKernelContext* context,
      const convolution_forward::primitive_desc& conv_prim_desc,
      const memory::dims& filter_dims_tf_order, Tensor** filter_tensor) {
    CHECK_NOTNULL(filter_tensor);
    auto filter_pd = conv_prim_desc.weights_primitive_desc();

    // Allocate shape of Mkl tensor.
    MklDnnShape filter_mkl_shape;
    filter_mkl_shape.SetMklTensor(true);
    filter_mkl_shape.SetMklLayout(&filter_pd);
    filter_mkl_shape.SetElemType(MklDnnType<T>());

    // The format of the filter is actually OIhw8i8o, but TF doesn't support
    // this format. Just use format::blocked for now because the layout
    // is stored in the MKL data.
    filter_mkl_shape.SetTfLayout(filter_dims_tf_order.size(),
                                 filter_dims_tf_order, memory::format::blocked);

    // Allocate the data space for the filter to propagate as TF tensor.
    TensorShape filter_tf_shape;
    filter_tf_shape.AddDim((filter_pd.get_size() / sizeof(T)));

    AllocateOutputSetMklShape(context, kOutputIndex_Filter, filter_tensor,
                              filter_tf_shape, filter_mkl_shape);
  }

  // Prepare and execute net - checks for input and output reorders.
  void PrepareAndExecuteNet(
      const convolution_forward::primitive_desc& conv_prim_desc,
      MklDnnData<T>* src, MklDnnData<T>* filter, MklDnnData<T>* bias,
      MklDnnData<T>* output, Tensor* filter_out_tensor) {
    CHECK_NOTNULL(filter_out_tensor);

    // Create reorders between user layout and MKL layout if it is needed and
    // add it to the net before convolution. No need to check for output
    // reorder as we propagate output layout to the next layer.
    src->CheckReorderToOpMem(conv_prim_desc.src_primitive_desc());

    // rather than re-order to a temp buffer, reorder directly to the
    // filter output tensor
    filter->CheckReorderToOpMem(conv_prim_desc.weights_primitive_desc(),
                                filter->GetTensorBuffer(filter_out_tensor));

    // Create convolution primitive and add it to net.
    std::vector<primitive> net;
    if (bias) {
      CHECK_EQ(biasEnabled, true);
      net.push_back(convolution_forward(conv_prim_desc, src->GetOpMem(),
                                        filter->GetOpMem(), bias->GetOpMem(),
                                        output->GetOpMem()));
    } else {
      CHECK_EQ(biasEnabled, false);
      net.push_back(convolution_forward(conv_prim_desc, src->GetOpMem(),
                                        filter->GetOpMem(),
                                        output->GetOpMem()));
    }

    stream(stream::kind::eager).submit(net).wait();
  }
};

#endif

// Register 2D operations
#define REGISTER_MKL_CPU_2D(T)                                      \
  REGISTER_KERNEL_BUILDER(Name("_MklConv2D")                        \
                              .Device(DEVICE_CPU)                   \
                              .TypeConstraint<T>("T")               \
                              .Label(mkl_op_registry::kMklOpLabel), \
                          MklConvOp<CPUDevice, T, false>);          \
  REGISTER_KERNEL_BUILDER(Name("_MklConv2DWithBias")                \
                              .Device(DEVICE_CPU)                   \
                              .TypeConstraint<T>("T")               \
                              .Label(mkl_op_registry::kMklOpLabel), \
                          MklConvOp<CPUDevice, T, true>);           \
  REGISTER_KERNEL_BUILDER(Name("__MklDummyConv2DWithBias")          \
                              .Device(DEVICE_CPU)                   \
                              .TypeConstraint<T>("T")               \
                              .Label(mkl_op_registry::kMklOpLabel), \
                          MklDummyOp<CPUDevice, T>);

TF_CALL_float(REGISTER_MKL_CPU_2D);

// Register 3D operations
#define REGISTER_MKL_CPU_3D(T)                                      \
  REGISTER_KERNEL_BUILDER(Name("_MklConv3D")                        \
                              .Device(DEVICE_CPU)                   \
                              .TypeConstraint<T>("T")               \
                              .Label(mkl_op_registry::kMklOpLabel), \
                          MklConvOp<CPUDevice, T, false>);
TF_CALL_float(REGISTER_MKL_CPU_3D);

}  // namespace tensorflow
#endif  // INTEL_MKL
