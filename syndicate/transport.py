from preserves import parse

constructors = {}

class InvalidTransportAddress(ValueError): pass

# decorator
def address(address_class):
    def k(connection_factory_class):
        constructors[address_class] = connection_factory_class
        return connection_factory_class
    return k

def connection_from_str(s, **kwargs):
    address = parse(s)
    for (address_class, factory_class) in constructors.items():
        decoded_address = address_class.try_decode(address)
        if decoded_address is not None:
            return factory_class(decoded_address, **kwargs)
    raise InvalidTransportAddress('Invalid transport address', address)
