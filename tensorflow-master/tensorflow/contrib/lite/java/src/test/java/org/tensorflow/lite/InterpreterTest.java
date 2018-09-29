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

package org.tensorflow.lite;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.fail;

import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.Map;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

/** Unit tests for {@link org.tensorflow.lite.Interpreter}. */
@RunWith(JUnit4.class)
public final class InterpreterTest {

  private static final File MODEL_FILE =
      new File("tensorflow/contrib/lite/java/src/testdata/add.bin");

  private static final File MOBILENET_MODEL_FILE =
      new File("tensorflow/contrib/lite/java/src/testdata/mobilenet.tflite.bin");

  @Test
  public void testInterpreter() throws Exception {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    assertThat(interpreter).isNotNull();
    assertThat(interpreter.getInputTensorCount()).isEqualTo(1);
    assertThat(interpreter.getInputTensor(0).dataType()).isEqualTo(DataType.FLOAT32);
    assertThat(interpreter.getOutputTensorCount()).isEqualTo(1);
    assertThat(interpreter.getOutputTensor(0).dataType()).isEqualTo(DataType.FLOAT32);
    interpreter.close();
  }

  @Test
  public void testInterpreterWithOptions() throws Exception {
    Interpreter interpreter =
        new Interpreter(MODEL_FILE, new Interpreter.Options().setNumThreads(2).setUseNNAPI(true));
    assertThat(interpreter).isNotNull();
    assertThat(interpreter.getInputTensorCount()).isEqualTo(1);
    assertThat(interpreter.getInputTensor(0).dataType()).isEqualTo(DataType.FLOAT32);
    assertThat(interpreter.getOutputTensorCount()).isEqualTo(1);
    assertThat(interpreter.getOutputTensor(0).dataType()).isEqualTo(DataType.FLOAT32);
    interpreter.close();
  }

  @Test
  public void testRunWithMappedByteBufferModel() throws Exception {
    Path path = MODEL_FILE.toPath();
    FileChannel fileChannel =
        (FileChannel) Files.newByteChannel(path, EnumSet.of(StandardOpenOption.READ));
    ByteBuffer mappedByteBuffer =
        fileChannel.map(FileChannel.MapMode.READ_ONLY, 0, fileChannel.size());
    Interpreter interpreter = new Interpreter(mappedByteBuffer);
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    float[][][][] parsedOutputs = new float[2][8][8][3];
    interpreter.run(fourD, parsedOutputs);
    float[] outputOneD = parsedOutputs[0][0][0];
    float[] expected = {3.69f, 19.62f, 23.43f};
    assertThat(outputOneD).usingTolerance(0.1f).containsExactly(expected).inOrder();
    interpreter.close();
    fileChannel.close();
  }

  @Test
  public void testRunWithDirectByteBufferModel() throws Exception {
    Path path = MODEL_FILE.toPath();
    FileChannel fileChannel =
        (FileChannel) Files.newByteChannel(path, EnumSet.of(StandardOpenOption.READ));
    ByteBuffer byteBuffer = ByteBuffer.allocateDirect((int) fileChannel.size());
    byteBuffer.order(ByteOrder.nativeOrder());
    fileChannel.read(byteBuffer);
    Interpreter interpreter = new Interpreter(byteBuffer);
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    float[][][][] parsedOutputs = new float[2][8][8][3];
    interpreter.run(fourD, parsedOutputs);
    float[] outputOneD = parsedOutputs[0][0][0];
    float[] expected = {3.69f, 19.62f, 23.43f};
    assertThat(outputOneD).usingTolerance(0.1f).containsExactly(expected).inOrder();
    interpreter.close();
    fileChannel.close();
  }

  @Test
  public void testRunWithInvalidByteBufferModel() throws Exception {
    Path path = MODEL_FILE.toPath();
    FileChannel fileChannel =
        (FileChannel) Files.newByteChannel(path, EnumSet.of(StandardOpenOption.READ));
    ByteBuffer byteBuffer = ByteBuffer.allocate((int) fileChannel.size());
    byteBuffer.order(ByteOrder.nativeOrder());
    fileChannel.read(byteBuffer);
    try {
      new Interpreter(byteBuffer);
      fail();
    } catch (IllegalArgumentException e) {
      assertThat(e)
          .hasMessageThat()
          .contains(
              "Model ByteBuffer should be either a MappedByteBuffer"
                  + " of the model file, or a direct ByteBuffer using ByteOrder.nativeOrder()");
    }
    fileChannel.close();
  }

  @Test
  public void testRun() {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    Float[] oneD = {1.23f, 6.54f, 7.81f};
    Float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    Float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    Float[][][][] fourD = {threeD, threeD};
    Float[][][][] parsedOutputs = new Float[2][8][8][3];
    try {
      interpreter.run(fourD, parsedOutputs);
      fail();
    } catch (IllegalArgumentException e) {
      assertThat(e).hasMessageThat().contains("cannot resolve DataType of [[[[Ljava.lang.Float;");
    }
    interpreter.close();
  }

  @Test
  public void testRunWithBoxedInputs() {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    float[][][][] parsedOutputs = new float[2][8][8][3];
    interpreter.run(fourD, parsedOutputs);
    float[] outputOneD = parsedOutputs[0][0][0];
    float[] expected = {3.69f, 19.62f, 23.43f};
    assertThat(outputOneD).usingTolerance(0.1f).containsExactly(expected).inOrder();
    interpreter.close();
  }

  @Test
  public void testRunForMultipleInputsOutputs() {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    Object[] inputs = {fourD};
    float[][][][] parsedOutputs = new float[2][8][8][3];
    Map<Integer, Object> outputs = new HashMap<>();
    outputs.put(0, parsedOutputs);
    interpreter.runForMultipleInputsOutputs(inputs, outputs);
    float[] outputOneD = parsedOutputs[0][0][0];
    float[] expected = {3.69f, 19.62f, 23.43f};
    assertThat(outputOneD).usingTolerance(0.1f).containsExactly(expected).inOrder();
    interpreter.close();
  }

  @Test
  public void testRunWithByteBufferOutput() {
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    ByteBuffer parsedOutput =
        ByteBuffer.allocateDirect(2 * 8 * 8 * 3 * 4).order(ByteOrder.nativeOrder());
    try (Interpreter interpreter = new Interpreter(MODEL_FILE)) {
      interpreter.run(fourD, parsedOutput);
    }
    float[] outputOneD = {
      parsedOutput.getFloat(0), parsedOutput.getFloat(4), parsedOutput.getFloat(8)
    };
    float[] expected = {3.69f, 19.62f, 23.43f};
    assertThat(outputOneD).usingTolerance(0.1f).containsExactly(expected).inOrder();
  }

  @Test
  public void testResizeInput() {
    try (Interpreter interpreter = new Interpreter(MODEL_FILE)) {
      int[] inputDims = {1};
      interpreter.resizeInput(0, inputDims);
      assertThat(interpreter.getInputTensor(0).shape()).isEqualTo(inputDims);
      ByteBuffer input = ByteBuffer.allocateDirect(4).order(ByteOrder.nativeOrder());
      ByteBuffer output = ByteBuffer.allocateDirect(4).order(ByteOrder.nativeOrder());
      interpreter.run(input, output);
      assertThat(interpreter.getOutputTensor(0).shape()).isEqualTo(inputDims);
    }
  }

  @Test
  public void testMobilenetRun() {
    // Create a gray image.
    float[][][][] img = new float[1][224][224][3];
    for (int i = 0; i < 224; ++i) {
      for (int j = 0; j < 224; ++j) {
        img[0][i][j][0] = 0.5f;
        img[0][i][j][1] = 0.5f;
        img[0][i][j][2] = 0.5f;
      }
    }

    // Allocate memory to receive the output values.
    float[][] labels = new float[1][1001];

    Interpreter interpreter = new Interpreter(MOBILENET_MODEL_FILE);
    interpreter.run(img, labels);
    assertThat(interpreter.getInputTensor(0).shape()).isEqualTo(new int[] {1, 224, 224, 3});
    assertThat(interpreter.getOutputTensor(0).shape()).isEqualTo(new int[] {1, 1001});
    interpreter.close();

    assertThat(labels[0])
        .usingExactEquality()
        .containsNoneOf(new float[] {Float.NaN, Float.NEGATIVE_INFINITY, Float.POSITIVE_INFINITY});
  }

  @Test
  public void testRunWithWrongInputType() {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    int[] oneD = {4, 3, 9};
    int[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    int[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    int[][][][] fourD = {threeD, threeD};
    float[][][][] parsedOutputs = new float[2][8][8][3];
    try {
      interpreter.run(fourD, parsedOutputs);
      fail();
    } catch (IllegalArgumentException e) {
      assertThat(e)
          .hasMessageThat()
          .contains(
              "Cannot convert between a TensorFlowLite tensor with type "
                  + "FLOAT32 and a Java object of type [[[[I (which is compatible with the"
                  + " TensorFlowLite type INT32)");
    }
    interpreter.close();
  }

  @Test
  public void testRunWithWrongOutputType() {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    int[][][][] parsedOutputs = new int[2][8][8][3];
    try {
      interpreter.run(fourD, parsedOutputs);
      fail();
    } catch (IllegalArgumentException e) {
      assertThat(e)
          .hasMessageThat()
          .contains(
              "Cannot convert between a TensorFlowLite tensor with type "
                  + "FLOAT32 and a Java object of type [[[[I (which is compatible with the"
                  + " TensorFlowLite type INT32)");
    }
    interpreter.close();
  }

  @Test
  public void testGetInputIndex() {
    Interpreter interpreter = new Interpreter(MOBILENET_MODEL_FILE);
    try {
      interpreter.getInputIndex("WrongInputName");
      fail();
    } catch (IllegalArgumentException e) {
      assertThat(e)
          .hasMessageThat()
          .contains(
              "'WrongInputName' is not a valid name for any input. Names of inputs and their "
                  + "indexes are {input=0}");
    }
    int index = interpreter.getInputIndex("input");
    assertThat(index).isEqualTo(0);
  }

  @Test
  public void testGetOutputIndex() {
    Interpreter interpreter = new Interpreter(MOBILENET_MODEL_FILE);
    try {
      interpreter.getOutputIndex("WrongOutputName");
      fail();
    } catch (IllegalArgumentException e) {
      assertThat(e)
          .hasMessageThat()
          .contains(
              "'WrongOutputName' is not a valid name for any output. Names of outputs and their"
                  + " indexes are {MobilenetV1/Predictions/Softmax=0}");
    }
    int index = interpreter.getOutputIndex("MobilenetV1/Predictions/Softmax");
    assertThat(index).isEqualTo(0);
  }

  @Test
  public void testTurnOnNNAPI() throws Exception {
    Path path = MODEL_FILE.toPath();
    FileChannel fileChannel =
        (FileChannel) Files.newByteChannel(path, EnumSet.of(StandardOpenOption.READ));
    MappedByteBuffer mappedByteBuffer =
        fileChannel.map(FileChannel.MapMode.READ_ONLY, 0, fileChannel.size());
    Interpreter interpreter =
        new Interpreter(
            mappedByteBuffer,
            new Interpreter.Options().setUseNNAPI(true).setAllowFp16PrecisionForFp32(true));
    float[] oneD = {1.23f, 6.54f, 7.81f};
    float[][] twoD = {oneD, oneD, oneD, oneD, oneD, oneD, oneD, oneD};
    float[][][] threeD = {twoD, twoD, twoD, twoD, twoD, twoD, twoD, twoD};
    float[][][][] fourD = {threeD, threeD};
    float[][][][] parsedOutputs = new float[2][8][8][3];
    interpreter.run(fourD, parsedOutputs);
    float[] outputOneD = parsedOutputs[0][0][0];
    float[] expected = {3.69f, 19.62f, 23.43f};
    assertThat(outputOneD).usingTolerance(0.1f).containsExactly(expected).inOrder();
    interpreter.close();
    fileChannel.close();
  }

  @Test
  public void testRedundantClose() throws Exception {
    Interpreter interpreter = new Interpreter(MODEL_FILE);
    interpreter.close();
    interpreter.close();
  }
}
