#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

from typing import Any
from typing import Callable
from typing import Iterable
from typing import Optional
from typing import TypeVar


class Session(object):
  """A session represents a mapping of expressions to concrete values.

  The bindings typically include required placeholders, but may be any
  intermediate expression as well.
  """
  def __init__(self, bindings=None):
    self._bindings = dict(bindings or {})

  def evaluate(self, expr):  # type: (Expression) -> Any
    if expr not in self._bindings:
      self._bindings[expr] = expr.evaluate_at(self)
    return self._bindings[expr]

  def lookup(self, expr):  #  type: (Expression) -> Any
    return self._bindings[expr]


# The return type of an Expression
T = TypeVar('T')


class Expression(object):
  """An expression is an operation bound to a set of arguments.

  An expression represents a deferred tree of operations, which can be
  evaluated at a specific bindings of root expressions to values.
  """
  def __init__(
      self,
      name,  # type: str
      proxy,  # type: T
      _id=None  # type: Optional[str]
  ):
    self._name = name
    self._proxy = proxy
    # Store for preservation through pickling.
    self._id = _id or '%s_%s' % (name, id(self))

  def proxy(self):  # type: () -> T
    return self._proxy

  def __hash__(self):
    return hash(self._id)

  def __eq__(self, other):
    return self._id == other._id

  def __ne__(self, other):
    return not self == other

  def evaluate_at(self, session):  # type: (Session) -> T
    """Returns the result of self with the bindings given in session."""
    raise NotImplementedError(type(self))

  def requires_partition_by_index(self):  # type: () -> bool
    """Whether this expression requires its argument(s) to be partitioned
    by index."""
    # TODO: It might be necessary to support partitioning by part of the index,
    # for some args, which would require returning more than a boolean here.
    raise NotImplementedError(type(self))

  def preserves_partition_by_index(self):  # type: () -> bool
    """Whether the result of this expression will be partitioned by index
    whenever all of its inputs are partitioned by index."""
    raise NotImplementedError(type(self))


class PlaceholderExpression(Expression):
  """An expression whose value must be explicitly bound in the session."""
  def __init__(
      self,  # type: PlaceholderExpression
      proxy  # type: T
  ):
    """Initialize a placeholder expression.

    Args:
      proxy: A proxy object with the type expected to be bound to this
        expression. Used for type checking at pipeline construction time.
    """
    super(PlaceholderExpression, self).__init__('placeholder', proxy)

  def args(self):
    return ()

  def evaluate_at(self, session):
    return session.lookup(self)

  def requires_partition_by_index(self):
    return False

  def preserves_partition_by_index(self):
    return False


class ConstantExpression(Expression):
  """An expression whose value is known at pipeline construction time."""
  def __init__(
      self,  # type: ConstantExpression
      value,  # type: T
      proxy=None  # type: Optional[T]
  ):
    """Initialize a constant expression.

    Args:
      value: The constant value to be produced by this expression.
      proxy: (Optional) a proxy object with same type as `value` to use for
        rapid type checking at pipeline construction time. If not provided,
        `value` will be used directly.
    """
    if proxy is None:
      proxy = value
    super(ConstantExpression, self).__init__('constant', proxy)
    self._value = value

  def args(self):
    return ()

  def evaluate_at(self, session):
    return self._value

  def requires_partition_by_index(self):
    return False

  def preserves_partition_by_index(self):
    return False


class ComputedExpression(Expression):
  """An expression whose value must be computed at pipeline execution time."""
  def __init__(
      self,  # type: ComputedExpression
      name,  # type: str
      func,  # type: Callable[...,T]
      args,  # type: Iterable[Expression]
      proxy=None,  # type: Optional[T]
      _id=None,  # type: Optional[str]
      requires_partition_by_index=True,  # type: bool
      preserves_partition_by_index=False,  # type: bool
  ):
    """Initialize a computed expression.

    Args:
      name: The name of this expression.
      func: The function that will be used to compute the value of this
        expression. Should accept arguments of the types returned when
        evaluating the `args` expressions.
      args: The list of expressions that will be used to produce inputs to
        `func`.
      proxy: (Optional) a proxy object with same type as the objects that this
        ComputedExpression will produce at execution time. If not provided, a
        proxy will be generated using `func` and the proxies of `args`.
      _id: (Optional) a string to uniquely identify this expression.
      requires_partition_by_index: Whether this expression requires its
        argument(s) to be partitioned by index.
      preserves_partition_by_index: Whether the result of this expression will
        be partitioned by index whenever all of its inputs are partitioned by
        index.
    """
    args = tuple(args)
    if proxy is None:
      proxy = func(*(arg.proxy() for arg in args))
    super(ComputedExpression, self).__init__(name, proxy, _id)
    self._func = func
    self._args = args
    self._requires_partition_by_index = requires_partition_by_index
    self._preserves_partition_by_index = preserves_partition_by_index

  def args(self):
    return self._args

  def evaluate_at(self, session):
    return self._func(*(arg.evaluate_at(session) for arg in self._args))

  def requires_partition_by_index(self):
    return self._requires_partition_by_index

  def preserves_partition_by_index(self):
    return self._preserves_partition_by_index


def elementwise_expression(name, func, args):
  return ComputedExpression(
      name,
      func,
      args,
      requires_partition_by_index=False,
      preserves_partition_by_index=True)
