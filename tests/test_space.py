"""Espaco livre e alocacao com restricao de banco."""

from rom_translator.core.space import SpaceAllocator, find_free_space


def test_finds_runs_of_each_filler():
    data = bytes(64) + b"dados" + b"\xff" * 64 + b"x"
    regions = find_free_space(data, min_run=32)
    assert [(r.start, r.end, r.filler) for r in regions] == [
        (0, 64, 0x00),
        (69, 133, 0xFF),
    ]


def test_ignores_runs_below_the_minimum():
    assert find_free_space(bytes(10) + b"x" + bytes(10), min_run=32) == []


def test_exclude_carves_a_region_in_two():
    regions = find_free_space(bytes(300), min_run=32, exclude=[(100, 140)])
    assert [(r.start, r.end) for r in regions] == [(0, 100), (140, 300)]


def test_exclude_can_remove_a_region_entirely():
    assert find_free_space(bytes(64), min_run=32, exclude=[(0, 64)]) == []


def test_allocator_hands_out_sequential_offsets():
    allocator = SpaceAllocator(find_free_space(bytes(256), min_run=32))
    assert allocator.allocate(10) == 0
    assert allocator.allocate(10) == 10
    assert allocator.total_used == 20


def test_allocator_refuses_when_nothing_fits():
    allocator = SpaceAllocator(find_free_space(bytes(64), min_run=32))
    assert allocator.allocate(100) is None


def test_regions_are_split_at_bank_boundaries():
    """Sem isso, uma regiao a cavalo de dois bancos nao serve nenhum dos dois."""
    allocator = SpaceAllocator(find_free_space(bytes(0x300), min_run=32), bank_size=0x100)
    assert [(r.start, r.end) for r in allocator.regions] == [
        (0, 0x100),
        (0x100, 0x200),
        (0x200, 0x300),
    ]


def test_allocation_respects_the_requested_bank():
    allocator = SpaceAllocator(find_free_space(bytes(0x300), min_run=32), bank_size=0x100)
    assert allocator.allocate(16, bank=2) == 0x200
    assert allocator.allocate(16, bank=0) == 0x000
    assert allocator.allocate(16, bank=9) is None


def test_free_by_bank_reports_each_bank_separately():
    allocator = SpaceAllocator(find_free_space(bytes(0x200), min_run=32), bank_size=0x100)
    allocator.allocate(0x40, bank=0)
    assert allocator.free_by_bank() == {0: 0xC0, 1: 0x100}
