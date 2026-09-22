import aircontrol


def test_package_metadata():
    assert hasattr(aircontrol, "__version__")
    assert aircontrol.__version__ == "0.1.0"
