__all__ = ('llrp', 'llrp_decoder', 'llrp_proto', 'util')
__version__ = '0.1.6'


class LLRPError (Exception):
    pass


class LLRPResponseError (LLRPError):
    pass
