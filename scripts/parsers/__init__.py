from .ss import parse_ss
from .vmess import parse_vmess

protocol_parsers = {
    "ss": parse_ss,
    "vmess": parse_vmess,
}
