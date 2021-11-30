def __load():
    from preserves.schema import load_schema_file
    import pathlib
    for (n, ns) in load_schema_file(pathlib.Path(__file__).parent /
                                    'protocols/schema-bundle.bin')._items().items():
        globals()[n] = ns
__load()
