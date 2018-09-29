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

#include <unordered_set>

#include "tensorflow/core/framework/attr_value.pb.h"
#include "tensorflow/core/framework/op.h"
#include "tensorflow/core/framework/types.h"
#include "tensorflow/core/grappler/op_types.h"
#include "tensorflow/core/grappler/utils.h"
#include "tensorflow/core/lib/core/status.h"
#include "tensorflow/core/lib/strings/str_util.h"
#include "tensorflow/core/platform/logging.h"

namespace tensorflow {
namespace grappler {

bool IsAdd(const NodeDef& node) {
  if (node.op() == "AddV2" || node.op() == "Add") {
    DataType type = node.attr().at("T").type();
    return type != DT_STRING;
  }
  return false;
}

bool IsAddN(const NodeDef& node) { return node.op() == "AddN"; }

bool IsAll(const NodeDef& node) { return node.op() == "All"; }

bool IsAngle(const NodeDef& node) { return node.op() == "Angle"; }

bool IsAny(const NodeDef& node) { return node.op() == "Any"; }

bool IsAnyDiv(const NodeDef& node) {
  return node.op() == "RealDiv" || node.op() == "Div" ||
         node.op() == "FloorDiv" || node.op() == "TruncateDiv";
}

bool IsApproximateEqual(const NodeDef& node) {
  return node.op() == "ApproximateEqual";
}

bool IsAvgPoolGrad(const NodeDef& node) { return node.op() == "AvgPoolGrad"; }

bool IsAssign(const NodeDef& node) {
  return node.op() == "Assign" || node.op() == "AssignVariableOp";
}

bool IsAssert(const NodeDef& node) { return node.op() == "Assert"; }

bool IsAtan2(const NodeDef& node) { return node.op() == "Atan2"; }

bool IsBetainc(const NodeDef& node) { return node.op() == "Betainc"; }

bool IsBiasAdd(const NodeDef& node) {
  return node.op() == "BiasAdd" || node.op() == "BiasAddV1";
}

bool IsBiasAddGrad(const NodeDef& node) { return node.op() == "BiasAddGrad"; }

bool IsBitcast(const NodeDef& node) { return node.op() == "Bitcast"; }

bool IsCast(const NodeDef& node) { return node.op() == "Cast"; }

bool IsCheckNumerics(const NodeDef& node) {
  return node.op() == "CheckNumerics";
}

bool IsCollective(const NodeDef& node) {
  return node.op() == "CollectiveReduce" ||
         node.op() == "CollectiveBcastSend" ||
         node.op() == "CollectiveBcastRecv";
}

bool IsComplex(const NodeDef& node) { return node.op() == "Complex"; }

bool IsComplexAbs(const NodeDef& node) { return node.op() == "ComplexAbs"; }

bool IsConcat(const NodeDef& node) {
  return node.op() == "Concat" || node.op() == "ConcatV2";
}

bool IsConcatOffset(const NodeDef& node) { return node.op() == "ConcatOffset"; }

bool IsConstant(const NodeDef& node) { return node.op() == "Const"; }

bool IsConj(const NodeDef& node) { return node.op() == "Conj"; }

bool IsConjugateTranspose(const NodeDef& node) {
  return node.op() == "ConjugateTranspose";
}

bool IsConv2D(const NodeDef& node) { return node.op() == "Conv2D"; }

bool IsConv2DBackpropFilter(const NodeDef& node) {
  return node.op() == "Conv2DBackpropFilter";
}

bool IsConv2DBackpropInput(const NodeDef& node) {
  return node.op() == "Conv2DBackpropInput";
}

bool IsConv3D(const NodeDef& node) { return node.op() == "Conv3D"; }

bool IsDepthwiseConv2dNative(const NodeDef& node) {
  return node.op() == "DepthwiseConv2dNative";
}

bool IsDepthwiseConv2dNativeBackpropFilter(const NodeDef& node) {
  return node.op() == "DepthwiseConv2dNativeBackpropFilter";
}

bool IsDepthwiseConv2dNativeBackpropInput(const NodeDef& node) {
  return node.op() == "DepthwiseConv2dNativeBackpropInput";
}

bool IsDequeueOp(const NodeDef& node) {
  const auto& op = node.op();
  return op == "QueueDequeueManyV2" || op == "QueueDequeueMany" ||
         op == "QueueDequeueV2" || op == "QueueDequeue" ||
         op == "QueueDequeueUpToV2" || op == "QueueDequeueUpTo";
}

bool IsDiv(const NodeDef& node) { return node.op() == "Div"; }

// Returns true if node represents a unary elementwise function that is
// monotonic. If *is_non_decreasing is true, the function is non-decreasing,
// e.g. sqrt, exp. *is_non_decreasing is false, the function is non-increasing,
// e.g. inv.
bool IsElementWiseMonotonic(const NodeDef& node, bool* is_non_decreasing) {
  static const std::unordered_set<string>* monotonic_non_decreasing_ops =
      CHECK_NOTNULL((new std::unordered_set<string>{
          "Asinh", "Atanh",   "Ceil",  "Elu",  "Erf",  "Exp",   "Expm1",
          "Floor", "Log",     "Log1p", "Relu", "Relu", "Relu6", "Rint",
          "Selu",  "Sigmoid", "Sign",  "Sinh", "Sqrt", "Tanh",
      }));
  static const std::unordered_set<string>* monotonic_non_increasing_ops =
      CHECK_NOTNULL((new std::unordered_set<string>{
          "Inv",
          "Reciprocal",
          "Erfc",
          "Rsqrt",
          "Neg",
      }));
  if (monotonic_non_decreasing_ops->count(node.op()) > 0) {
    if (is_non_decreasing) {
      *is_non_decreasing = true;
    }
    return true;
  } else if (monotonic_non_increasing_ops->count(node.op()) > 0) {
    if (is_non_decreasing) {
      *is_non_decreasing = false;
    }
    return true;
  }
  return false;
}

bool IsEluGrad(const NodeDef& node) { return node.op() == "EluGrad"; }

bool IsEnter(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Enter" || op == "RefEnter";
}

bool IsEqual(const NodeDef& node) { return node.op() == "Equal"; }

bool IsExit(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Exit" || op == "RefExit";
}

bool IsExp(const NodeDef& node) { return node.op() == "Exp"; }

bool IsFill(const NodeDef& node) { return node.op() == "Fill"; }

bool IsFloorDiv(const NodeDef& node) { return node.op() == "FloorDiv"; }

bool IsFloorMod(const NodeDef& node) { return node.op() == "FloorMod"; }

bool IsFusedBatchNormGrad(const NodeDef& node) {
  const auto& op = node.op();
  return op == "FusedBatchNormGrad" || op == "FusedBatchNormGradV2";
}

bool IsGreater(const NodeDef& node) { return node.op() == "Greater"; }

bool IsGreaterEqual(const NodeDef& node) { return node.op() == "GreaterEqual"; }

bool IsHistogramSummary(const NodeDef& node) {
  return node.op() == "HistogramSummary";
}

bool IsIdentity(const NodeDef& node) {
  const auto& op = node.op();
  if (op == "IdentityN" && node.attr().at("T").list().type_size() == 1) {
    return true;
  }
  return op == "Identity" || op == "RefIdentity";
}

bool IsIdentityN(const NodeDef& node) {
  const auto& op = node.op();
  return op == "IdentityN";
}

bool IsIgamma(const NodeDef& node) { return node.op() == "Igamma"; }

bool IsIgammac(const NodeDef& node) { return node.op() == "Igammac"; }

bool IsImag(const NodeDef& node) { return node.op() == "Imag"; }

bool IsInvGrad(const NodeDef& node) { return node.op() == "InvGrad"; }

bool IsLess(const NodeDef& node) { return node.op() == "Less"; }

bool IsLessEqual(const NodeDef& node) { return node.op() == "LessEqual"; }

bool IsLog(const NodeDef& node) { return node.op() == "Log"; }

bool IsLogicalAnd(const NodeDef& node) { return node.op() == "LogicalAnd"; }

bool IsLogicalNot(const NodeDef& node) { return node.op() == "LogicalNot"; }

bool IsLogicalOr(const NodeDef& node) { return node.op() == "LogicalOr"; }

bool IsMatMul(const NodeDef& node) {
  const auto& op = node.op();
  return op == "MatMul" || op == "BatchMatMul" || op == "QuantizedMatMul" ||
         op == "SparseMatMul";
}

bool IsMax(const NodeDef& node) { return node.op() == "Max"; }

bool IsMaximum(const NodeDef& node) { return node.op() == "Maximum"; }

bool IsMaxPoolGrad(const NodeDef& node) { return node.op() == "MaxPoolGrad"; }

bool IsMean(const NodeDef& node) { return node.op() == "Mean"; }

bool IsMerge(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Merge" || op == "RefMerge";
}

bool IsMin(const NodeDef& node) { return node.op() == "Min"; }

bool IsMinimum(const NodeDef& node) { return node.op() == "Minimum"; }

bool IsMirrorPad(const NodeDef& node) { return node.op() == "MirrorPad"; }

bool IsMirrorPadGrad(const NodeDef& node) {
  return node.op() == "MirrorPadGrad";
}

bool IsMod(const NodeDef& node) { return node.op() == "Mod"; }

bool IsMul(const NodeDef& node) { return node.op() == "Mul"; }

bool IsNeg(const NodeDef& node) { return node.op() == "Neg"; }

bool IsNoOp(const NodeDef& node) { return node.op() == "NoOp"; }

bool IsNotEqual(const NodeDef& node) { return node.op() == "NotEqual"; }

bool IsNextIteration(const NodeDef& node) {
  const auto& op = node.op();
  return op == "NextIteration" || op == "RefNextIteration";
}

bool IsPack(const NodeDef& node) { return node.op() == "Pack"; }

bool IsPad(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Pad" || op == "PadV2";
}

bool IsPlaceholder(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Placeholder" || op == "PlaceholderV2" ||
         op == "PlaceholderWithDefault";
}

bool IsPolygamma(const NodeDef& node) { return node.op() == "Polygamma"; }

bool IsPow(const NodeDef& node) { return node.op() == "Pow"; }

bool IsPrint(const NodeDef& node) { return node.op() == "Print"; }

bool IsProd(const NodeDef& node) { return node.op() == "Prod"; }

bool IsQueue(const NodeDef& node) {
  return str_util::EndsWith(node.op(), "QueueV2");
}

bool IsRandomShuffle(const NodeDef& node) {
  return node.op() == "RandomShuffle";
}

bool IsRank(const NodeDef& node) { return node.op() == "Rank"; }

bool IsReal(const NodeDef& node) { return node.op() == "Real"; }

bool IsRealDiv(const NodeDef& node) { return node.op() == "RealDiv"; }

bool IsReciprocalGrad(const NodeDef& node) {
  return node.op() == "ReciprocalGrad";
}

bool IsRecv(const NodeDef& node) {
  return node.op() == "_Recv" || node.op() == "_HostRecv";
}

bool IsReduction(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Sum" || op == "Prod" || op == "Min" || op == "Max" ||
         op == "Mean" || op == "Any" || op == "All";
}

bool IsReluGrad(const NodeDef& node) { return node.op() == "ReluGrad"; }

bool IsRelu6Grad(const NodeDef& node) { return node.op() == "Relu6Grad"; }

bool IsReshape(const NodeDef& node) { return (node.op() == "Reshape"); }

bool IsRestore(const NodeDef& node) {
  return (node.op() == "Restore" || node.op() == "RestoreV2" ||
          node.op() == "RestoreSlice");
}

bool IsReverse(const NodeDef& node) {
  return node.op() == "Reverse" || node.op() == "ReverseV2";
}

bool IsReverseV2(const NodeDef& node) { return node.op() == "ReverseV2"; }

bool IsRsqrt(const NodeDef& node) { return node.op() == "Rsqrt"; }

bool IsRsqrtGrad(const NodeDef& node) { return node.op() == "RsqrtGrad"; }

bool IsSelect(const NodeDef& node) { return node.op() == "Select"; }

bool IsSeluGrad(const NodeDef& node) { return node.op() == "SeluGrad"; }

bool IsSend(const NodeDef& node) {
  return node.op() == "_Send" || node.op() == "_HostSend";
}

bool IsShape(const NodeDef& node) { return node.op() == "Shape"; }

bool IsShapeN(const NodeDef& node) { return node.op() == "ShapeN"; }

bool IsShuffle(const NodeDef& node) { return node.op() == "Shuffle"; }

bool IsSigmoidGrad(const NodeDef& node) { return node.op() == "SigmoidGrad"; }

bool IsSize(const NodeDef& node) { return node.op() == "Size"; }

bool IsSlice(const NodeDef& node) { return node.op() == "Slice"; }

bool IsSnapshot(const NodeDef& node) { return node.op() == "Snapshot"; }

bool IsSoftplusGrad(const NodeDef& node) { return node.op() == "SoftplusGrad"; }

bool IsSoftsignGrad(const NodeDef& node) { return node.op() == "SoftsignGrad"; }

bool IsSplit(const NodeDef& node) { return node.op() == "Split"; }

bool IsSplitV(const NodeDef& node) { return node.op() == "SplitV"; }

bool IsSqrt(const NodeDef& node) { return node.op() == "Sqrt"; }

bool IsSqrtGrad(const NodeDef& node) { return node.op() == "SqrtGrad"; }

bool IsSquare(const NodeDef& node) { return node.op() == "Square"; }

bool IsSquaredDifference(const NodeDef& node) {
  return node.op() == "SquaredDifference";
}

bool IsSqueeze(const NodeDef& node) { return node.op() == "Squeeze"; }

bool IsStackOp(const NodeDef& node) {
  return node.op() == "Stack" || node.op() == "StackV2";
}
bool IsStackCloseOp(const NodeDef& node) {
  return node.op() == "StackClose" || node.op() == "StackCloseV2";
}
bool IsStackPushOp(const NodeDef& node) {
  return node.op() == "StackPush" || node.op() == "StackPushV2";
}
bool IsStackPopOp(const NodeDef& node) {
  return node.op() == "StackPop" || node.op() == "StackPopV2";
}

bool IsStopGradient(const NodeDef& node) {
  const auto& op = node.op();
  return op == "StopGradient" || op == "PreventGradient";
}

bool IsStridedSlice(const NodeDef& node) { return node.op() == "StridedSlice"; }

bool IsStridedSliceGrad(const NodeDef& node) {
  return node.op() == "StridedSliceGrad";
}

bool IsSub(const NodeDef& node) { return node.op() == "Sub"; }

bool IsSum(const NodeDef& node) { return node.op() == "Sum"; }

bool IsSwitch(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Switch" || op == "RefSwitch";
}

bool IsTanhGrad(const NodeDef& node) { return node.op() == "TanhGrad"; }

bool IsTile(const NodeDef& node) { return node.op() == "Tile"; }

bool IsTranspose(const NodeDef& node) { return node.op() == "Transpose"; }

bool IsTruncateDiv(const NodeDef& node) { return node.op() == "TruncateDiv"; }

bool IsTruncateMod(const NodeDef& node) { return node.op() == "TruncateMod"; }

bool IsUnpack(const NodeDef& node) { return node.op() == "Unpack"; }

bool IsVariable(const NodeDef& node) {
  const auto& op = node.op();
  return op == "Variable" || op == "VariableV2" || op == "AutoReloadVariable" ||
         op == "VarHandleOp" || op == "ReadVariableOp";
}

bool IsZeta(const NodeDef& node) { return node.op() == "Zeta"; }

namespace {
bool GetBoolAttr(const NodeDef& node, const string& name) {
  return node.attr().count(name) > 0 && node.attr().at(name).b();
}
}  // namespace

bool IsPersistent(const NodeDef& node) {
  return IsConstant(node) || IsVariable(node);
}

bool MaybeHasRefInput(const NodeDef& node) {
  const OpDef* op_def;
  Status status = OpRegistry::Global()->LookUpOpDef(node.op(), &op_def);
  if (!status.ok()) {
    return true;
  }
  // Nodes such as Assign or AssignAdd modify one of their inputs.
  for (const auto& input : op_def->input_arg()) {
    if (input.is_ref()) {
      return true;
    }
  }
  return false;
}

bool IsFreeOfSideEffect(const NodeDef& node) {
  // Placeholders must be preserved to keep the graph feedable.
  if (IsPlaceholder(node)) {
    return false;
  }
  const OpDef* op_def = nullptr;
  const string& op_name = node.op();
  Status status = OpRegistry::Global()->LookUpOpDef(op_name, &op_def);
  if (!status.ok()) {
    return false;
  }
  if (op_def->is_stateful()) {
    return false;
  }
  // Nodes such as Assign or AssignAdd modify one of their inputs.
  for (const auto& input : op_def->input_arg()) {
    if (input.is_ref()) {
      return false;
    }
  }
  // Queue ops modify the queue which is a side effect.
  if (node.op().find("Queue") != string::npos) {
    return false;
  }
  return !ModifiesInputsInPlace(node);
}

bool ModifiesInputsInPlace(const NodeDef& node) {
  // Some nodes do in-place updates on regular tensor inputs.
  string op_name = node.op();

  // Ops that modify resource variables effectively modify one of their inputs.
  if (op_name == "AssignVariableOp" || op_name == "AssignAddVariableOp" ||
      op_name == "AssignSubVariableOp" || op_name == "ResourceScatterUpdate" ||
      op_name == "ResourceScatterAdd" || op_name == "ResourceScatterSub" ||
      op_name == "ResourceScatterMul" || op_name == "ResourceScatterDiv" ||
      op_name == "ResourceScatterMin" || op_name == "ResourceScatterMax") {
    return false;
  }

  std::transform(op_name.begin(), op_name.end(), op_name.begin(), ::tolower);
  if (str_util::StrContains(op_name, "inplace")) {
    return true;
  }
  return GetBoolAttr(node, "in_place") || GetBoolAttr(node, "inplace");
}

bool ModifiesFrameInfo(const NodeDef& node) {
  return IsEnter(node) || IsExit(node) || IsNextIteration(node);
}

#define OPDEF_PROPERTY_HELPER(PROPERTY_CAP, PROPERTY)                      \
  bool Is##PROPERTY_CAP(const NodeDef& node) {                             \
    if (node.op() == "Add") {                                              \
      /* Workaround for "Add" not being marked is_commutative and */       \
      /* is_aggregate. (See cl/173915048). */                              \
      const auto type = GetDataTypeFromAttr(node, "T");                    \
      return type != DT_INVALID && type != DT_STRING;                      \
    }                                                                      \
    const OpDef* op_def = nullptr;                                         \
    Status status = OpRegistry::Global()->LookUpOpDef(node.op(), &op_def); \
    return status.ok() && op_def->is_##PROPERTY();                         \
  }

OPDEF_PROPERTY_HELPER(Aggregate, aggregate)
OPDEF_PROPERTY_HELPER(Commutative, commutative)

bool IsInvolution(const NodeDef& node) {
  static const std::unordered_set<string>* involution_ops =
      CHECK_NOTNULL((new std::unordered_set<string>{
          "Conj", "Reciprocal", "Invert", "Neg", "LogicalNot"}));
  return involution_ops->count(node.op()) > 0;
}

bool IsValueAndOrderAndShapePreserving(const NodeDef& node) {
  if (NumNonControlInputs(node) == 1 && IsAggregate(node)) {
    return true;
  }
  static const std::unordered_set<string>*
      value_and_order_and_shape_preserving_ops =
          CHECK_NOTNULL((new const std::unordered_set<string>{
              "CheckNumerics",
              "DebugGradientIdentity",
              "DeepCopy"
              "Enter",
              "Exit",
              "PreventGradient",
              "Print",
              "Snapshot",
              "StopGradient",
          }));
  return value_and_order_and_shape_preserving_ops->count(node.op()) > 0 ||
         IsIdentity(node);
}

bool IsValueAndOrderPreserving(const NodeDef& node) {
  if (NumNonControlInputs(node) == 1 && IsAggregate(node)) {
    return true;
  }
  static const std::unordered_set<string>* value_and_order_preserving_ops =
      CHECK_NOTNULL((new const std::unordered_set<string>{
          "ExpandDims",
          "Reshape",
          "Squeeze",
      }));
  return value_and_order_preserving_ops->count(node.op()) > 0 ||
         IsValueAndOrderAndShapePreserving(node);
}

bool IsValuePreserving(const NodeDef& node) {
  static const std::unordered_set<string>* value_preserving_ops =
      CHECK_NOTNULL((new std::unordered_set<string>{
          "InvertPermutation",
          "Reverse",
          "Roll",
          "Transpose",
      }));
  return IsValueAndOrderPreserving(node) ||
         value_preserving_ops->count(node.op()) > 0;
}

bool IsUnaryElementWise(const NodeDef& node) {
  static const std::unordered_set<string>* element_wise_ops =
      CHECK_NOTNULL((new std::unordered_set<string>{
          "Abs",
          "Acos",
          "Acosh",
          "Asin",
          "Asinh",
          "Atan",
          "Atan2",
          "Atanh",
          "Ceil",
          "ComplexAbs",
          "Conj",
          "Cos",
          "Cosh",
          "Digamma",
          "Elu"
          "Erf",
          "Erfc",
          "Exp",
          "Expm1",
          "Floor",
          "Inv",
          "Invert",
          "Isinf",
          "Isnan",
          "Isfinite",
          "Lgamma",
          "Log",
          "Log1p",
          "LogicalNot",
          "Neg",
          "Reciprocal",
          "Relu",
          "Relu6",
          "Rint",
          "Round",
          "Selu",
          "Rsqrt",
          "Sigmoid",
          "Sign",
          "Sin",
          "SinH",
          "Softplus",
          "Softsign",
          "Sqrt",
          "Square",
          "Tan"
          "Tanh",
      }));
  return element_wise_ops->count(node.op()) > 0 ||
         IsValueAndOrderAndShapePreserving(node);
}

bool HasOpDef(const NodeDef& node) {
  const OpDef* op_def = nullptr;
  return OpRegistry::Global()->LookUpOpDef(node.op(), &op_def).ok();
}

bool IsIdempotent(const NodeDef& node) {
  return IsValueAndOrderAndShapePreserving(node) && IsFreeOfSideEffect(node) &&
         !ModifiesFrameInfo(node);
}

}  // namespace grappler
}  // end namespace tensorflow
