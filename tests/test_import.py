import os
modname = "application"
namespace = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

def test_import():
    __import__('{}.{}'.format(namespace, modname))
