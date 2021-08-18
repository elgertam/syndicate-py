class IdGenerator:
    def __init__(self, initial_value = 0):
        self.next = initial_value

    def __iter__(self):
        return self

    def __next__(self):
        n = self.next
        self.next = n + 1
        return n
