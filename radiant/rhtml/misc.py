class EmptyAttr:
    pass

class Property:
    def __init__(self, name, value):
        self.name = name
        self.value = value

class PClass(Property):
    def __init__(self, value):
        self.name = "class"
        self.value = value
