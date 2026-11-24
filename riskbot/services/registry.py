"""In-memory model registry (``ports.ModelRegistry``).

The registry is the lookup table the executor uses to turn a ``VariationSpec.model_id`` into a callable
``Model``. It starts empty; the composition root registers the core models.

Guarantees
----------
* ``register`` rejects a second model with the same ``spec.model_id`` (``ValidationFailed``) and objects
  that do not look like a ``Model`` (no ``spec`` / ``run``).
* ``get`` raises ``NotFound`` for an unknown id.
* ``specs`` returns specs in registration order, optionally filtered by question.
* Thread-safe: registration and lookup are guarded by a lock.
"""

from __future__ import annotations

import threading

from riskbot.contract.errors import NotFound, ValidationFailed
from riskbot.contract.ports import Model
from riskbot.contract.types import ModelSpec, QuestionId


class InMemoryRegistry:
    """Dictionary-backed ``ModelRegistry``; insertion order is preserved."""

    def __init__(self) -> None:
        self._models: dict[str, Model] = {}
        self._lock = threading.Lock()

    def register(self, model: Model) -> None:
        """Add ``model``; raise ``ValidationFailed`` if its id is already registered or it is not a Model."""
        spec = getattr(model, "spec", None)
        if not isinstance(spec, ModelSpec) or not callable(getattr(model, "run", None)):
            raise ValidationFailed("object is not a Model (needs a ModelSpec `spec` and a `run` method)")
        with self._lock:
            if spec.model_id in self._models:
                raise ValidationFailed(f"model {spec.model_id!r} is already registered", model_id=spec.model_id)
            self._models[spec.model_id] = model

    def get(self, model_id: str) -> Model:
        """Return the registered model or raise ``NotFound``."""
        with self._lock:
            try:
                return self._models[model_id]
            except KeyError:
                raise NotFound(f"unknown model {model_id!r}", model_id=model_id) from None

    def specs(self, question: QuestionId | None = None) -> list[ModelSpec]:
        """Specs of every registered model (registration order), optionally only those of ``question``."""
        with self._lock:
            models = list(self._models.values())
        return [m.spec for m in models if question is None or m.spec.question == question]

    def __len__(self) -> int:
        with self._lock:
            return len(self._models)
