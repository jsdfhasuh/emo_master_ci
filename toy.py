"""Independent synthetic fixture: bounded integer accumulator."""

class Counter:
    def __init__(self, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("negative capacity")
        self.capacity = capacity
        self.total = 0

    def add(self, amount: int) -> bool:
        if amount < 0:
            raise ValueError("negative amount")
        if self.total + amount > self.capacity:
            return False
        self.total += amount
        return True
