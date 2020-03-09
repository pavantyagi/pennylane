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
"""Rotosolve gradient free optimizer"""

from pennylane import numpy as np


class RotosolveOptimizer:
    r"""Rotosolve gradient free optimizer.

    The Rotosolve optimizer minimizes an objective function with respect to the parameters of a
    quantum circuit without the need of calculating the gradient of the function. The algorithm
    works by updating the parameters :math:`\theta = \theta_1, \dots, \theta_D` one at a time
    according to a closed-form expression for the optimal value of the :math:`d^{th}` parameter
    :math:`\theta^*_d` when the other parameters are fixed:

    .. math:: \theta^*_d = \underset{\theta_d}{\text{argmin}}\left<H\right>_{\theta_d}
              = -\frac{\pi}{2} - \text{arctan2}\left(2\left<H\right>_{\theta_d=0}
              - \left<H\right>_{\theta_d=\pi/2} - \left<H\right>_{\theta_d=-\pi/2},
              \left<H\right>_{\theta_d=\pi/2} - \left<H\right>_{\theta_d=-\pi/2}\right),

    where :math:`\left<H\right>_{\theta_d}` is the expectation value of the objective function
    optimized over the parameter :math:`\theta_d`.

    The algorithm is described in further detail in `Ostaszewski et al. (2019) <https://arxiv.org/abs/1905.09692>`_
    """
    # pylint: disable=too-few-public-methods

    def __init__(self):
        pass

    def step(self, objective_fn, x):
        """Update x with one step of the optimizer.

        Args:
            objective_fn (function): the objective function for optimization
            x (array): NumPy array containing the current values of the variables to be updated

        Returns:
            array: the new variable values :math:`x^{(t+1)}`
        """
        # make sure that x is an array
        if np.ndim(x) == 0:
            x = np.array([x])

        for d, _ in enumerate(x):
            x = self._rotosolve(objective_fn, x, d)

        return x

    @staticmethod
    def _rotosolve(objective_fn, x, d):
        """The rotosolve step for one parameter.

        Args:
            objective_fn (function): the objective function for optimization
            x (array): NumPy array containing the current values of the variables to be updated

        Returns:
            array: the input array ``x`` with the value at position ``d`` optimized
        """
        # helper function for x[d] = theta
        def insert(x, d, theta):
            x[d] = theta
            return x

        H_0 = float(objective_fn(insert(x, d, 0)))
        H_p = float(objective_fn(insert(x, d, np.pi / 2)))
        H_m = float(objective_fn(insert(x, d, -np.pi / 2)))

        a = np.arctan2(2 * H_0 - H_p - H_m, H_p - H_m)

        x[d] = -np.pi / 2 - a

        if x[d] <= -np.pi:
            x[d] += 2 * np.pi
        return x