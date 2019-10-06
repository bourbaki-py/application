{
'__main__': {
    'a': 1,
    'b': [
        1,
        2,
        3
    ],
    '[c]': 'YYYY-MM-DD'
},
'print': {
    'ns': {
        '[outfile]': '<text-file>',
        'pretty': False,
        'literal': False
    },
    'tuple': {
        'kwarg': {
            '[outfile]': '<text-file>',
            'tup': [
                '<int>',
                '<int> OR <int>[/<int>]',
                '<float>'
            ],
            'pretty': False,
            'literal': False
        },
        'pos': {
            'tup': [
                '<int>',
                '<int> OR <int>[/<int>]',
                '<float>'
            ],
            '[outfile]': '<text-file>',
            'pretty': False,
            'literal': False
        },
        'union-kwarg': {
            '[outfile]': '<text-file>',
            'tup': [
                [
                    '<int> OR <int>[/<int>]',
                    '<str>'
                ],
                'OR',
                [
                    '<str>',
                    '<bool>'
                ]
            ],
            'pretty': False,
            'literal': False
        }
    },
    'named-tuple': {
        'tup': dict(
            foo='foo',
            bar='.',
            baz='2019-08-27'
        ),
        '[outfile]': '<text-file>',
        'pretty': False,
        'literal': False
    },
    'enum': {
        '[foo]': 'foo|bar|baz',
        '[outfile]': '<text-file>',
        'pretty': False,
        'literal': False
    },
    'uuid': {
        '[uuid]': '[0-f]{32}',
        '[outfile]': '<text-file>',
        'pretty': False,
        'literal': False
    },
    'numbers': {
        '[x]': '<decimal-str>',
        '[y]': '<int>[/<int>]',
        '[z]': '<float>[+<float>j]',
        '[outfile]': '<text-file>',
        'pretty': False,
        'literal': False
    },
    'bytes': {
        '[outfile]': '<text-file>',
        'b': [
            '<0-255>',
            '...'
        ],
        'pretty': False,
        'literal': False
    },
    'url': {
        '[outfile]': '<text-file>',
        'url': 'scheme://netloc[/path][;params][?query][#fragment]',
        'pretty': False,
        'literal': False
    },
    'mapping': {
        '[outfile]': '<text-file>',
        'foo_to_date': {
            'foo|bar|baz': 'YYYY-MM-DD',
            '...': '...'
        },
        'pretty': False,
        'literal': False
    },
    'flags': dict(
        boolean1='{0|1|true|false}',
        boolean2=False,
        flag1=False,
        flag2=True
    )
},
'cant': dict(
    parse={
        '[outfile]': '<text-file>',
        'can_parse_me': [
            '<str>',
            '...'
        ],
        '[cant_parse_me]': [
            [
                [
                    '<str>',
                    '...'
                ],
                '...'
            ],
            'OR',
            None
        ],
        'pretty': False,
        'literal': False
    }
),
'args-and-kwargs': {
    '[outfile]': '<text-file>',
    'ips': [
        '<ipv6addr>',
        '...'
    ],
    'pretty': False,
    'literal': False,
    'named_ips': {
        '<str>': '<ipaddr>',
        '...': '...'
    }
},
'leading': dict(
    list={
        'i_2': '<int>',
        '[outfile]': '<text-file>',
        'l_1': [
            '<float>',
            '...'
        ],
        'pretty': False,
        'literal': False
    }
),
'types': {
    'number': 'path.to.type[type,params]',
    '[outfile]': '<text-file>',
    'pretty': False,
    'literal': False,
    'types': {
        '<str>': 'path.to.type[type,params]',
        '...': '...'
    }
},
'get': dict(
    attr={
        'attr': '<str>',
        '[outfile]': '<text-file>',
        'pretty': False,
        'literal': False
    }
),
'args': {
    'args': [
        'foo|bar|baz',
        '...'
    ],
    '[outfile]': '<text-file>',
    'pretty': False,
    'literal': False
},
'init': dict(
    config=dict(

    )
)
}
