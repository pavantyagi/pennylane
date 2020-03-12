# Copyright 2018-2020 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Tests for the pennylane.qnn module.
"""
import pytest
import os
import numpy as np
import tensorflow as tf
from tensorflow.keras.layers import Layer
from tensorflow.keras.initializers import RandomNormal
import tempfile

import pennylane as qml
from pennylane.qnn import KerasLayer


@pytest.fixture
def get_circuit(n_qubits, output_dim):
    """Fixture for getting a sample quantum circuit with a controllable qubit number and output
    dimension. Returns both the circuit and the shape of the weights."""

    dev = qml.device("default.qubit", wires=n_qubits)
    weight_shapes = {"w1": (3, n_qubits, 3), "w2": (1,), "w3": 1, "w4": [3], "w5": (2, n_qubits, 3)}

    @qml.qnode(dev, interface="tf")
    def circuit(inputs, w1, w2, w3, w4, w5):
        """A circuit that embeds data using the AngleEmbedding and then performs a variety of
        operations. The output is a PauliZ measurement on the first output_dim qubits. One set of
        parameters, w5, are specified as non-trainable."""
        qml.templates.AngleEmbedding(inputs, wires=list(range(n_qubits)))
        qml.templates.StronglyEntanglingLayers(w1, wires=list(range(n_qubits)))
        qml.RX(w2, wires=0)
        qml.RX(w3, wires=0)
        qml.Rot(*w4, wires=0)
        qml.templates.StronglyEntanglingLayers(w5, wires=list(range(n_qubits)))
        return [qml.expval(qml.PauliZ(i)) for i in range(output_dim)]

    return circuit, weight_shapes


@pytest.mark.usefixtures("get_circuit")
@pytest.fixture
def model(get_circuit, n_qubits, output_dim):
    """Fixture for creating a hybrid Keras model. The model is composed of KerasLayers sandwiched
    between Dense layers."""
    c, w = get_circuit
    layer1 = KerasLayer(c, w, output_dim)
    layer2 = KerasLayer(c, w, output_dim)

    model = tf.keras.models.Sequential(
        [
            tf.keras.layers.Dense(n_qubits),
            layer1,
            tf.keras.layers.Dense(n_qubits),
            layer2,
            tf.keras.layers.Dense(output_dim),
        ]
    )

    return model


def indices(n_max):
    """Returns an iterator over the number of qubits and output dimension, up to value n_max.
    The output dimension never exceeds the number of qubits."""
    a, b = np.tril_indices(n_max)
    return zip(*[a + 1, b + 1])


@pytest.mark.usefixtures("get_circuit")
class TestKerasLayer:
    """Unit tests for the pennylane.qnn.KerasLayer class."""

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_no_input(self, get_circuit, output_dim):
        """Test if a TypeError is raised when instantiated with a QNode that does not have an
        INPUT_ARG argument"""
        c, w = get_circuit
        del c.func.sig[qml.qnn.INPUT_ARG]
        with pytest.raises(TypeError, match="QNode must include an argument with name"):
            KerasLayer(c, w, output_dim)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_input_in_weight_shapes(self, get_circuit, n_qubits, output_dim):
        """Test if a ValueError is raised when instantiated with a weight_shapes dictionary that
        contains the shape of the input"""
        c, w = get_circuit
        w[qml.qnn.INPUT_ARG] = n_qubits
        with pytest.raises(
            ValueError, match="{} argument should not have its dimension".format(qml.qnn.INPUT_ARG)
        ):
            KerasLayer(c, w, output_dim)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_weight_shape_unspecified(self, get_circuit, output_dim):
        """Test if a ValueError is raised when instantiated with a weight missing from the
        weight_shapes dictionary"""
        c, w = get_circuit
        del w["w1"]
        with pytest.raises(ValueError, match="Must specify a shape for every non-input parameter"):
            KerasLayer(c, w, output_dim)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_var_pos(self, get_circuit, monkeypatch, output_dim):
        """Test if a TypeError is raised when instantiated with a variable number of positional
        arguments"""
        c, w = get_circuit

        class FuncPatch:
            """Patch for variable number of keyword arguments"""

            sig = c.func.sig
            var_pos = True
            var_keyword = False

        with monkeypatch.context() as m:
            m.setattr(c, "func", FuncPatch)

            with pytest.raises(TypeError, match="Cannot have a variable number of positional"):
                KerasLayer(c, w, output_dim)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_var_keyword(self, get_circuit, monkeypatch, output_dim):
        """Test if a TypeError is raised when instantiated with a variable number of keyword
        arguments"""
        c, w = get_circuit

        class FuncPatch:
            """Patch for variable number of keyword arguments"""

            sig = c.func.sig
            var_pos = False
            var_keyword = True

        with monkeypatch.context() as m:
            m.setattr(c, "func", FuncPatch)

            with pytest.raises(TypeError, match="Cannot have a variable number of keyword"):
                KerasLayer(c, w, output_dim)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    @pytest.mark.parametrize("input_dim", zip(*[[None, [1], (1,), 1], [None, 1, 1, 1]]))
    def test_input_dim(self, get_circuit, input_dim, output_dim):
        """Test if the input_dim is correctly processed, i.e., that an iterable is mapped to
        its first element while an int or None is left unchanged."""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim, input_dim[0])
        assert layer.input_dim == input_dim[1]

    @pytest.mark.parametrize("n_qubits", [1])
    @pytest.mark.parametrize("output_dim", zip(*[[[1], (1,), 1], [1, 1, 1]]))
    def test_output_dim(self, get_circuit, output_dim):
        """Test if the output_dim is correctly processed, i.e., that an iterable is mapped to
        its first element while an int is left unchanged."""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim[0])
        assert layer.output_dim == output_dim[1]

    @pytest.mark.parametrize("n_qubits, output_dim", indices(2))
    def test_weight_shapes(self, get_circuit, output_dim, n_qubits):
        """Test if the weight_shapes input argument is correctly processed to be a dictionary
        with values that are tuples."""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim)
        assert layer.weight_shapes == {
            "w1": (3, n_qubits, 3),
            "w2": (1,),
            "w3": (1,),
            "w4": (3,),
            "w5": (2, n_qubits, 3),
        }

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_non_input_defaults(self, get_circuit, output_dim, n_qubits):
        """Test if a TypeError is raised when default arguments that are not INPUT_ARG are
        present in the QNode"""
        c, w = get_circuit

        @qml.qnode(qml.device("default.qubit", wires=n_qubits), interface="tf")
        def c_dummy(inputs, w1, w2, w3, w4, w5, w6=None):
            """Dummy version of the circuit with a default argument"""
            return c(inputs, w1, w2, w3, w4, w5)

        with pytest.raises(
            TypeError, match="Only the argument {} is permitted".format(qml.qnn.INPUT_ARG)
        ):
            KerasLayer(c_dummy, {**w, **{"w6": 1}}, output_dim)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    @pytest.mark.parametrize("weight_specs", zip(*[[None, {"w1": {}}], [{}, {"w1": {}}]]))
    def test_weight_specs_initialize(self, get_circuit, output_dim, weight_specs):
        """Test if the weight_specs input argument is correctly processed, so that it
        initializes to an empty dictionary if not specified but is left unchanged if already a
        dictionary"""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim, weight_specs=weight_specs[0])
        assert layer.weight_specs == weight_specs[1]

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_build_wrong_input_shape(self, get_circuit, output_dim):
        """Test if the build() method raises a ValueError if the user has specified an input
        dimension but build() is called with a different dimension. Note that the input_shape
        passed to build is a tuple to include a batch dimension"""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim, input_dim=4)
        with pytest.raises(ValueError, match="QNode can only accept inputs of size"):
            layer.build(input_shape=(10, 3))

    @pytest.mark.parametrize("n_qubits, output_dim", indices(2))
    def test_qnode_weights(self, get_circuit, n_qubits, output_dim):
        """Test if the build() method correctly initializes the weights in the qnode_weights
        dictionary, i.e., that each value of the dictionary has correct shape and name."""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim)
        layer.build(input_shape=(10, n_qubits))

        for weight, shape in layer.weight_shapes.items():
            assert layer.qnode_weights[weight].shape == shape
            assert layer.qnode_weights[weight].name[:-2] == weight

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_qnode_weights_with_spec(self, get_circuit, monkeypatch, output_dim, n_qubits):
        """Test if the build() method correctly passes on user specified weight_specs to the
        inherited add_weight() method. This is done by monkeypatching add_weight() so that it
        simply returns its input keyword arguments. The qnode_weights dictionary should then have
        values that are the input keyword arguments, and we check that the specified weight_specs
        keywords are there."""

        def add_weight_dummy(*args, **kwargs):
            """Dummy function for mocking out the add_weight method to simply return the input
            keyword arguments"""
            return kwargs

        weight_specs = {
            "w1": {"initializer": "random_uniform", "trainable": False},
            "w2": {"initializer": RandomNormal(mean=0, stddev=0.5)},
            "w3": {},
            "w4": {},
            "w5": {},
        }

        with monkeypatch.context() as m:
            m.setattr(Layer, "add_weight", add_weight_dummy)
            c, w = get_circuit
            layer = KerasLayer(c, w, output_dim, weight_specs=weight_specs)
            layer.build(input_shape=(10, n_qubits))

            for weight in layer.weight_shapes:
                assert all(
                    item in layer.qnode_weights[weight].items()
                    for item in weight_specs[weight].items()
                )

    @pytest.mark.parametrize("n_qubits, output_dim", indices(3))
    @pytest.mark.parametrize("input_shape", [(10, 4), (8, 3)])
    def test_compute_output_shape(self, get_circuit, output_dim, input_shape):
        """Test if the compute_output_shape() method performs correctly, i.e., that it replaces
        the last element in the input_shape tuple with the specified output_dim and that the
        output shape is of type tf.TensorShape"""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim)

        assert layer.compute_output_shape(input_shape) == (input_shape[0], output_dim)
        assert isinstance(layer.compute_output_shape(input_shape), tf.TensorShape)

    @pytest.mark.parametrize("n_qubits, output_dim", indices(4))
    @pytest.mark.parametrize("batch_size", [5, 10, 15])
    def test_call(self, get_circuit, output_dim, batch_size, n_qubits):
        """Test if the call() method performs correctly, i.e., that it outputs with shape
        (batch_size, output_dim) with results that agree with directly calling the QNode"""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim)
        x = tf.ones((batch_size, n_qubits))

        layer_out = layer(x)
        weights = [w[0] if w.shape == (1,) else w for w in layer.qnode_weights.values()]

        assert layer_out.shape == (batch_size, output_dim)
        assert np.allclose(layer_out[0], c(x[0], *weights))

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    @pytest.mark.parametrize("batch_size", [5])
    def test_call_shuffled_args(self, get_circuit, output_dim, batch_size, n_qubits):
        """Test if the call() method performs correctly when the inputs argument is not the first
        positional argument, i.e., that it outputs with shape (batch_size, output_dim) with
        results that agree with directly calling the QNode"""
        c, w = get_circuit

        @qml.qnode(qml.device("default.qubit", wires=n_qubits), interface="tf")
        def c_shuffled(w1, inputs, w2, w3, w4, w5):
            """Version of the circuit with a shuffled signature"""
            qml.templates.AngleEmbedding(inputs, wires=list(range(n_qubits)))
            qml.templates.StronglyEntanglingLayers(w1, wires=list(range(n_qubits)))
            qml.RX(w2, wires=0)
            qml.RX(w3, wires=0)
            qml.Rot(*w4, wires=0)
            qml.templates.StronglyEntanglingLayers(w5, wires=list(range(n_qubits)))
            return [qml.expval(qml.PauliZ(i)) for i in range(output_dim)]

        layer = KerasLayer(c_shuffled, w, output_dim)
        x = tf.ones((batch_size, n_qubits))

        layer_out = layer(x)
        weights = [w[0] if w.shape == (1,) else w for w in layer.qnode_weights.values()]

        assert layer_out.shape == (batch_size, output_dim)
        assert np.allclose(layer_out[0], c(x[0], *weights))

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    @pytest.mark.parametrize("batch_size", [5])
    def test_call_default_input(self, get_circuit, output_dim, batch_size, n_qubits):
        """Test if the call() method performs correctly when the inputs argument is a default
        argument, i.e., that it outputs with shape (batch_size, output_dim) with results that
        agree with directly calling the QNode"""
        c, w = get_circuit

        @qml.qnode(qml.device("default.qubit", wires=n_qubits), interface="tf")
        def c_default(w1, w2, w3, w4, w5, inputs=None):
            """Version of the circuit with inputs as a default argument"""
            qml.templates.AngleEmbedding(inputs, wires=list(range(n_qubits)))
            qml.templates.StronglyEntanglingLayers(w1, wires=list(range(n_qubits)))
            qml.RX(w2, wires=0)
            qml.RX(w3, wires=0)
            qml.Rot(*w4, wires=0)
            qml.templates.StronglyEntanglingLayers(w5, wires=list(range(n_qubits)))
            return [qml.expval(qml.PauliZ(i)) for i in range(output_dim)]

        layer = KerasLayer(c_default, w, output_dim)
        x = tf.ones((batch_size, n_qubits))

        layer_out = layer(x)
        weights = [w[0] if w.shape == (1,) else w for w in layer.qnode_weights.values()]

        assert layer_out.shape == (batch_size, output_dim)
        assert np.allclose(layer_out[0], c(x[0], *weights))

    @pytest.mark.parametrize("n_qubits, output_dim", indices(1))
    def test_str_repr(self, get_circuit, output_dim):
        """Test the __str__ and __repr__ representations"""
        c, w = get_circuit
        layer = KerasLayer(c, w, output_dim)

        assert layer.__str__() == "<Quantum Keras layer: func=circuit>"
        assert layer.__repr__() == "<Quantum Keras layer: func=circuit>"


@pytest.mark.usefixtures("get_circuit", "model")
class TestKerasLayerIntegration:
    """Integration tests for the pennylane.qnn.KerasLayer class."""

    @pytest.mark.parametrize("n_qubits, output_dim", indices(2))
    @pytest.mark.parametrize("batch_size", [5, 10])
    def test_train_model(self, model, batch_size, n_qubits, output_dim):
        """Test if a model can train using the KerasLayer. The model is composed of a single
        KerasLayer sandwiched between two Dense layers, and the dataset is simply input and output
        vectors of zeros. The test checks that the loss function after two epochs is less than
        the loss function after one epoch, indicating that training is taking place."""

        x = np.zeros((5, n_qubits))
        y = np.zeros((5, output_dim))

        model.compile(optimizer="sgd", loss="mse")

        result = model.fit(x, y, epochs=2, batch_size=batch_size, verbose=0)
        loss = result.history["loss"]

        assert loss[0] > loss[-1]

    @pytest.mark.parametrize("n_qubits, output_dim", indices(2))
    def test_model_gradients(self, model, output_dim, n_qubits):
        """Test if a gradient can be calculated with respect to all of the trainable variables in
        the model"""
        x = tf.zeros((5, n_qubits))
        y = tf.zeros((5, output_dim))

        with tf.GradientTape() as tape:
            out = model(x)
            loss = tf.keras.losses.mean_squared_error(out, y)

        gradients = tape.gradient(loss, model.trainable_variables)
        assert all([not isinstance(g, type(None)) for g in gradients])

    @pytest.mark.parametrize("n_qubits, output_dim", indices(2))
    def test_model_save_weights(self, model, n_qubits):
        """Test if the model can be successfully saved and reloaded using the get_weights()
        method"""
        _, filename = tempfile.mkstemp()
        prediction = model.predict(np.ones(n_qubits))
        weights = model.get_weights()
        model.save_weights(filename)
        model.load_weights(filename)
        prediction_loaded = model.predict(np.ones(n_qubits))
        weights_loaded = model.get_weights()

        assert np.allclose(prediction, prediction_loaded)
        for i, w in enumerate(weights):
            assert np.allclose(w, weights_loaded[i])

        os.remove(filename)