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
from collections.abc import Iterable
import functools
import inspect
from typing import Optional

import tensorflow as tf

from pennylane.qnodes import QNode
from pennylane.interfaces.tf import to_tf

if int(tf.__version__.split(".")[0]) < 2:
    raise ImportError("TensorFlow version 2 or above is required for this module")
else:
    from tensorflow.keras.layers import Layer


class KerasLayer(Layer):
    def __init__(
        self,
        qnode: QNode,
        weight_shapes: dict,
        output_dim: int,
        input_dim: Optional[int] = None,
        weight_specs: Optional[dict] = None,
        **kwargs
    ):

        self.sig = qnode.func.sig
        defaults = [
            name for name, sig in self.sig.items() if sig.par.default != inspect.Parameter.empty
        ]
        if len(defaults) != 1:
            raise TypeError("Conversion to a Keras layer requires a QNode with a single "
                            "default argument")
        self.input_arg = defaults[0]

        if self.input_arg in set(weight_shapes.keys()):
            raise ValueError("Input argument dimension should not be specified in weight_shapes")
        if set(weight_shapes.keys()) | set(self.input_arg) != set(self.sig.keys()):
            raise ValueError("Must specify a shape for every non-input parameter in the QNode")
        if qnode.func.var_pos:
            raise TypeError("Cannot have a variable number of positional arguments")
        if qnode.func.var_keyword:
            raise TypeError("Cannot have a variable number of keyword arguments")

        self.qnode = to_tf(qnode, dtype=tf.keras.backend.floatx())
        self.input_dim = input_dim[0] if isinstance(input_dim, Iterable) else input_dim
        self.weight_shapes = {
            weight: (tuple(size) if isinstance(size, Iterable) else (size,))
            for weight, size in weight_shapes.items()
        }
        self.output_dim = output_dim[0] if isinstance(output_dim, Iterable) else output_dim

        if weight_specs:
            self.weight_specs = weight_specs
        else:
            self.weight_specs = {}
        self.qnode_weights = {}

        super(KerasLayer, self).__init__(dynamic=True, **kwargs)

    def build(self, input_shape):
        if self.input_dim and input_shape[-1] != self.input_dim:
            raise ValueError("QNode can only accept inputs of size {}".format(self.input_dim))

        for weight, size in self.weight_shapes.items():
            spec = self.weight_specs.get(weight, {})
            self.qnode_weights[weight] = self.add_weight(name=weight, shape=size, **spec)

        super(KerasLayer, self).build(input_shape)

    def call(self, inputs, **kwargs):
        qnode = self.qnode
        for arg in self.sig:
            if arg is not self.input_arg:
                w = self.qnode_weights[arg]
                if w.shape == (1,):
                    qnode = functools.partial(qnode, w[0])
                else:
                    qnode = functools.partial(qnode, w)

        outputs = tf.stack([qnode(**{self.input_arg: x}) for x in inputs])
        input_shape = tf.shape(inputs)

        return tf.reshape(outputs, self.compute_output_shape(input_shape))

    def compute_output_shape(self, input_shape):
        return tf.TensorShape([input_shape[0], self.output_dim])

    def __str__(self):
        detail = "<Quantum Keras layer: func={}>"
        return detail.format(self.qnode.func.__name__)

    def __repr__(self):
        return self.__str__()
