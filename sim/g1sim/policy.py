"""Unitree's pretrained G1 walking policy, run in numpy -- no torch.

`motion.pt` is a TorchScript archive of `PolicyExporterLSTM` from unitree_rl_gym:

    obs (47) -> LSTM(hidden 64, 1 layer) -> Linear(64, 32) -> ELU -> Linear(32, 12)

with the LSTM's hidden and cell state kept *between* calls. That recurrence is why a
reset must zero the state: carried over, the previous episode's gait would leak into
the first steps of the next.

Loaded by reading the archive's pickle directly, so neither the simulator image nor the
robot needs torch for a 40k-parameter network. `tests` in `sim/tests/` check the port
against torch whenever torch is importable.
"""

from __future__ import annotations

import io
import pickle
import zipfile
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_DTYPES = {"FloatStorage": np.float32, "DoubleStorage": np.float64}


class _ScriptModule(SimpleNamespace):
    """Stands in for every `__torch__.*` class: the pickle only sets its attributes."""

    def __setstate__(self, state):
        self.__dict__.update(state)


class _Storage:
    def __init__(self, name: str):
        self.name = name


def _load_tensors(path: Path):
    """The archive's root object, with every tensor as a numpy array."""
    with zipfile.ZipFile(path) as archive:
        pickles = [n for n in archive.namelist() if n.endswith("/data.pkl")]
        if len(pickles) != 1:
            raise ValueError(f"{path}: expected one data.pkl, found {pickles}")
        prefix = pickles[0][: -len("data.pkl")]
        byteorder = archive.read(prefix + "byteorder").decode().strip() \
            if prefix + "byteorder" in archive.namelist() else "little"
        endian = "<" if byteorder == "little" else ">"

        def rebuild(storage, offset, size, stride, *_):
            dtype_name, key = storage
            dtype = np.dtype(_DTYPES[dtype_name]).newbyteorder(endian)
            flat = np.frombuffer(archive.read(f"{prefix}data/{key}"), dtype=dtype)
            if not size:
                return flat[offset:offset + 1].reshape(()).astype(np.float32)
            item = flat.itemsize
            view = np.lib.stride_tricks.as_strided(
                flat[offset:], shape=tuple(size), strides=tuple(s * item for s in stride))
            return np.array(view, dtype=np.float32)

        class Unpickler(pickle.Unpickler):
            def find_class(self, module, name):
                if module == "torch._utils" and name == "_rebuild_tensor_v2":
                    return rebuild
                if module == "torch" and name in _DTYPES:
                    return name
                if module == "collections" and name == "OrderedDict":
                    return OrderedDict
                if module == "torch.jit._pickle":
                    # TorchScript's typed-container markers; the value is all we need.
                    if name == "restore_type_tag":
                        return lambda value, _type_tag: value
                    if name.startswith("build_"):
                        return lambda value: value
                if module.startswith("__torch__"):
                    return _ScriptModule
                raise pickle.UnpicklingError(f"refusing to load {module}.{name}")

            def persistent_load(self, pid):
                kind, storage_type, key, _location, _numel = pid
                if kind != "storage":
                    raise pickle.UnpicklingError(f"unexpected persistent id {pid!r}")
                return (storage_type, key)

        return Unpickler(io.BytesIO(archive.read(pickles[0]))).load()


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _elu(x: np.ndarray) -> np.ndarray:
    return np.where(x > 0.0, x, np.expm1(np.minimum(x, 0.0)))


class LstmPolicy:
    """`action = policy(obs)`, stateful across calls; `reset()` zeroes the memory."""

    def __init__(self, *, w_ih, w_hh, b_ih, b_hh, w1, b1, w2, b2):
        self.w_ih, self.w_hh = w_ih.astype(np.float32), w_hh.astype(np.float32)
        self.b = (b_ih + b_hh).astype(np.float32)
        self.w1, self.b1 = w1.astype(np.float32), b1.astype(np.float32)
        self.w2, self.b2 = w2.astype(np.float32), b2.astype(np.float32)
        self.hidden_size = self.w_hh.shape[1]
        self.input_size = self.w_ih.shape[1]
        self.output_size = self.w2.shape[0]
        self.reset()

    @classmethod
    def load(cls, path: str | Path) -> "LstmPolicy":
        root = _load_tensors(Path(path))
        memory, actor = root.memory, root.actor
        first, last = getattr(actor, "0"), getattr(actor, "2")
        return cls(w_ih=memory.weight_ih_l0, w_hh=memory.weight_hh_l0,
                   b_ih=memory.bias_ih_l0, b_hh=memory.bias_hh_l0,
                   w1=first.weight, b1=first.bias, w2=last.weight, b2=last.bias)

    def reset(self) -> None:
        self.h = np.zeros(self.hidden_size, dtype=np.float32)
        self.c = np.zeros(self.hidden_size, dtype=np.float32)

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        x = np.asarray(obs, dtype=np.float32).reshape(self.input_size)
        gates = self.w_ih @ x + self.w_hh @ self.h + self.b
        i, f, g, o = np.split(gates, 4)               # PyTorch's gate order
        self.c = _sigmoid(f) * self.c + _sigmoid(i) * np.tanh(g)
        self.h = _sigmoid(o) * np.tanh(self.c)
        return self.w2 @ _elu(self.w1 @ self.h + self.b1) + self.b2
