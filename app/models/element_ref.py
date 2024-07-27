from typing import Literal, NamedTuple, NewType, Self, override

from app.validators.element_type import element_type

ElementId = NewType('ElementId', int)
ElementType = Literal['node', 'way', 'relation']


class ElementRef(NamedTuple):
    type: ElementType
    id: ElementId

    @classmethod
    def from_str(cls, s: str) -> Self:
        """
        Parse an element reference from a string representation.

        >>> ElementRef.from_str('n123')
        ElementRef(type='node', id=123)
        """
        type = element_type(s)
        id = ElementId(int(s[1:]))
        if id == 0:
            raise ValueError('Element id cannot be 0')
        return cls(type, id)

    @override
    def __str__(self) -> str:
        """
        Produce a string representation of the element reference.

        >>> ElementRef(ElementType.node, 123)
        'n123'
        """
        return f'{self.type[0]}{self.id}'


class VersionedElementRef(NamedTuple):
    type: ElementType
    id: ElementId
    version: int

    @classmethod
    def from_str(cls, s: str) -> Self:
        """
        Parse a versioned element reference from a string representation.

        >>> VersionedElementRef.from_str('n123v1')
        VersionedElementRef(type='node', id=123, version=1)
        """
        type = element_type(s)
        idx = s.rindex('v')
        id = ElementId(int(s[1:idx]))
        version = int(s[idx + 1 :])
        if id == 0:
            raise ValueError('Element id cannot be 0')
        if version <= 0:
            raise ValueError('Element version must be positive')
        return cls(type, id, version)

    @classmethod
    def from_type_str(cls, type: ElementType, s: str) -> Self:
        """
        Parse a versioned element reference from a string.

        >>> VersionedElementRef.from_type_str(ElementType.node, '123v1')
        VersionedElementRef(type='node', id=123, version=1)
        """
        idx = s.rindex('v')
        id = ElementId(int(s[:idx]))
        version = int(s[idx + 1 :])
        if id == 0:
            raise ValueError('Element id cannot be 0')
        if version <= 0:
            raise ValueError('Element version must be positive')
        return cls(type, id, version)

    @override
    def __str__(self) -> str:
        """
        Produce a string representation of the versioned element reference.

        >>> VersionedElementRef(ElementType.node, 123, 1)
        'n123v1'
        """
        return f'{self.type[0]}{self.id}v{self.version}'
