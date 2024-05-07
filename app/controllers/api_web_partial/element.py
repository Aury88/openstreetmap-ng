from collections.abc import Sequence

from anyio import create_task_group
from fastapi import APIRouter
from pydantic import PositiveInt

from app.lib.element_list_formatter import format_element_members
from app.lib.feature_name import feature_name
from app.lib.render_response import render_response
from app.lib.statement_context import joinedload_context, loadonly_context
from app.lib.tags_format import tags_format
from app.lib.translation import t
from app.models.db.element import Element
from app.models.element_list_entry import ElementMemberEntry
from app.models.element_ref import ElementRef
from app.models.element_type import ElementType
from app.models.tag_format import TagFormatCollection
from app.repositories.element_repository import ElementRepository
from app.utils import JSON_ENCODE

router = APIRouter(prefix='/element')


@router.get('/{type}/{id:int}')
async def get_element(type: ElementType, id: PositiveInt):
    with joinedload_context(Element.changeset):
        ref = ElementRef(type, id)
        elements = await ElementRepository.get_many_latest_by_element_refs((ref,), limit=1)
        element = elements[0] if elements else None

    if element is None:
        return render_response(
            'partial/not_found.jinja2',
            {'type': type, 'id': id},
        )

    is_latest = False
    elements: Sequence[ElementMemberEntry] | None = None

    async def check_latest_task():
        nonlocal is_latest
        is_latest = await ElementRepository.is_latest(element.versioned_ref)

    async def elements_task():
        nonlocal elements
        with loadonly_context(Element.type, Element.id, Element.tags):
            elements_ = await ElementRepository.get_many_latest_by_element_refs(element.members, limit=None)
            elements = format_element_members(element.members, elements_)

    async with create_task_group() as tg:
        tg.start_soon(check_latest_task)
        if element.members:
            tg.start_soon(elements_task)

    changeset_tags_ = element.changeset.tags
    if 'comment' in changeset_tags_:
        changeset_tags = tags_format(changeset_tags_)
        comment_tag = changeset_tags['comment']
    else:
        comment_tag = TagFormatCollection('comment', t('browse.no_comment'))

    prev_version = element.version - 1 if element.version > 1 else None
    next_version = element.version + 1 if not is_latest else None
    name = feature_name(element.tags)
    tags = tags_format(element.tags)

    return render_response(
        'partial/element.jinja2',
        {
            'element': element,
            'changeset': element.changeset,
            'prev_version': prev_version,
            'next_version': next_version,
            'name': name,
            'tags': tags.values(),
            'comment_tag': comment_tag,
            'elements_len': len(elements) if (elements is not None) else None,
            'params': JSON_ENCODE(
                {
                    'type': type,
                    'id': id,
                    # TODO: part of data
                    'elements': elements,
                }
            ).decode(),
        },
    )
