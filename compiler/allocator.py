"""Storage and function ID allocator for the TTDoom compiler.

Manages the assignment of TrueType storage slot indices (for variables
and arrays) and FDEF function IDs during compilation.  The allocator
tracks three kinds of names:

* **Variables** -- each occupies a single storage slot (``RS[]`` / ``WS[]``).
* **Arrays** -- occupy a contiguous range of storage slots starting at a
  base index.
* **Constants** -- compile-time values that are inlined as ``PUSH`` instructions
  and never consume storage.
* **Functions** -- each user-defined or stdlib function receives a unique
  FDEF ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class AllocatorError(Exception):
    """Raised when the allocator detects an invalid operation."""


@dataclass
class StorageAllocator:
    """Assigns storage indices and function IDs.

    Args:
        start_storage: First available storage slot index.
        start_func_id: First available FDEF function ID.
    """

    _next_storage: int = 0
    _next_func_id: int = 0

    # name -> storage index
    vars: dict[str, int] = field(default_factory=dict)

    # name -> compile-time integer value
    consts: dict[str, int] = field(default_factory=dict)

    # name -> (base_index, size)
    arrays: dict[str, tuple[int, int]] = field(default_factory=dict)

    # name -> FDEF id
    funcs: dict[str, int] = field(default_factory=dict)

    # func_name -> [param_names]  (parameter order matches source declaration)
    func_params: dict[str, list[str]] = field(default_factory=dict)

    # func_name -> {param_name: storage_idx}  (storage for function locals)
    func_local_storage: dict[str, dict[str, int]] = field(default_factory=dict)

    def alloc_var(self, name: str) -> int:
        """Allocate a single storage slot for a variable.

        Args:
            name: Variable name.

        Returns:
            Assigned storage slot index.

        Raises:
            AllocatorError: If the name is already declared.
        """
        if name in self.vars:
            raise AllocatorError(f"Variable '{name}' already declared")
        idx = self._next_storage
        self.vars[name] = idx
        self._next_storage += 1
        return idx

    def alloc_array(self, name: str, size: int) -> int:
        """Allocate a contiguous range of storage slots for an array.

        Args:
            name: Array name.
            size: Number of elements.

        Returns:
            Base storage slot index.

        Raises:
            AllocatorError: If the name is already declared.
        """
        if name in self.arrays:
            raise AllocatorError(f"Array '{name}' already declared")
        base = self._next_storage
        self.arrays[name] = (base, size)
        self._next_storage += size
        return base

    def alloc_func(self, name: str) -> int:
        """Allocate a function ID for an FDEF.

        Args:
            name: Function name.

        Returns:
            Assigned FDEF function ID.

        Raises:
            AllocatorError: If the name is already declared.
        """
        if name in self.funcs:
            raise AllocatorError(f"Function '{name}' already declared")
        fid = self._next_func_id
        self.funcs[name] = fid
        self._next_func_id += 1
        return fid

    def alloc_func_locals(self, func_name: str, param_names: list[str]) -> dict[str, int]:
        """Allocate storage slots for function parameters.

        Parameters are stored in storage slots so they can be referenced
        by name inside the function body.

        Args:
            func_name: Name of the function.
            param_names: Ordered list of parameter names.

        Returns:
            Mapping of parameter name to its storage slot index.
        """
        self.func_params[func_name] = list(param_names)
        locals_map: dict[str, int] = {}
        for pname in param_names:
            idx = self._next_storage
            locals_map[pname] = idx
            self._next_storage += 1
        self.func_local_storage[func_name] = locals_map
        return locals_map

    def define_const(self, name: str, value: int) -> None:
        """Register a compile-time constant.

        Args:
            name: Constant name.
            value: Integer value (inlined at every use site).

        Raises:
            AllocatorError: If the name is already declared.
        """
        if name in self.consts:
            raise AllocatorError(f"Constant '{name}' already declared")
        self.consts[name] = value

    def lookup(self, name: str) -> tuple[str, int]:
        """Look up a name in the symbol table.

        Searches constants, then variables, then arrays.

        Args:
            name: The identifier to look up.

        Returns:
            Tuple of ``('const', value)``, ``('var', storage_index)``,
            or ``('array', base_index)``.

        Raises:
            KeyError: If the name is not defined.
        """
        if name in self.consts:
            return ("const", self.consts[name])
        if name in self.vars:
            return ("var", self.vars[name])
        if name in self.arrays:
            return ("array", self.arrays[name][0])
        raise KeyError(f"Undefined name: '{name}'")

    @property
    def total_storage(self) -> int:
        """Total number of storage slots allocated so far."""
        return self._next_storage

    @property
    def total_funcs(self) -> int:
        """Total number of function IDs allocated so far."""
        return self._next_func_id
