from datetime import datetime

import pytest

from app.lib.xmltodict import XMLToDict, get_xattr


@pytest.mark.parametrize(
    ('input', 'output'),
    [
        (
            b'<root><key1 attr="1"/><key2>text</key2><key1 attr="2"/></root>',
            {'root': {'key1': [{'@attr': '1'}, {'@attr': '2'}], 'key2': 'text'}},
        ),
        (
            b'<root><key1 attr="1"/><key2>text</key2><key2 attr="2">text2</key2></root>',
            {
                'root': {
                    'key1': {'@attr': '1'},
                    'key2': ['text', {'#text': 'text2', '@attr': '2'}],
                }
            },
        ),
        (
            b'<osmChange><modify id="1"/><create id="2"><tag k="test" v="zebra"/></create><modify id="3"/></osmChange>',
            {
                'osmChange': [
                    ('modify', {'@id': 1}),
                    ('create', {'@id': 2, 'tag': [{'@k': 'test', '@v': 'zebra'}]}),
                    ('modify', {'@id': 3}),
                ]
            },
        ),
    ],
)
def test_xml_parse(input, output):
    assert XMLToDict.parse(input) == output


@pytest.mark.parametrize(
    ('input', 'output'),
    [
        (
            b'<osmChange><modify id="1"/><create id="2"><tag k="test" v="zebra"/></create><modify id="3"/></osmChange>',
            {
                'osmChange': [
                    ('modify', {'@id': 1}),
                    ('create', {'@id': 2, 'tag': [{'@k': 'test', '@v': 'zebra'}]}),
                    ('modify', {'@id': 3}),
                ]
            },
        ),
    ],
)
def test_xml_parse_sequence(input, output):
    assert XMLToDict.parse(input) == output


@pytest.mark.parametrize(
    ('input', 'output'),
    [
        (
            {
                'osmChange': [
                    ('@attrib', 'yes'),
                    ('modify', '1'),
                    ('create', '2'),
                    ('modify', '3'),
                    (
                        'modify',
                        {
                            '@id': '4',
                            '@timestamp': datetime(2020, 1, 1),
                            '@visible': True,
                        },
                    ),
                ]
            },
            '<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n<osmChange attrib="yes"><modify>1</modify><create>2</create><modify>3</modify><modify id="4" timestamp="2020-01-01T00:00:00Z" visible="true"/></osmChange>',
        ),
        (
            {
                'osmChange': {
                    'create': [],
                    'modify': [
                        {'@id': 1},
                        {
                            '@id': 2,
                            'tag': [
                                {'@k': 'test', '@v': 'zebra'},
                                {'@k': 'test2', '@v': 'zebra2'},
                            ],
                        },
                        {},
                    ],
                    'delete': {'@id': 3},
                }
            },
            '<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n<osmChange><modify id="1"/><modify id="2"><tag k="test" v="zebra"/><tag k="test2" v="zebra2"/></modify><modify/><delete id="3"/></osmChange>',
        ),
        (
            {'root': {'#text': 'text'}},
            "<?xml version='1.0' encoding='UTF-8'?>\n<root>text</root>",
        ),
    ],
)
def test_xml_unparse(input, output):
    assert XMLToDict.unparse(input) == output


def test_xml_unparse_xattr():
    xattr = get_xattr(is_json=False)
    unparsed = XMLToDict.unparse({'root': {xattr('test', xml='test_xml'): 'test_value'}})
    expected = "<?xml version='1.0' encoding='UTF-8'?>\n<root test_xml=\"test_value\"/>"
    assert unparsed == expected


def test_xml_unparse_invalid_multi_root():
    with pytest.raises(ValueError):
        XMLToDict.unparse({'root1': {}, 'root2': {}})


def test_xml_unparse_empty():
    unparsed = XMLToDict.unparse({'root': []})
    expected = "<?xml version='1.0' encoding='UTF-8'?>\n<root/>"
    assert unparsed == expected
