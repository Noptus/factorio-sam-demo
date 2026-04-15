"""
Few-shot examples: LOGISTICS (belts, inserters, power)
=======================================================
Pattern:
    calculate_belt_path()
    →  place_belt_segment() (tile-by-tile or helper)
    →  place_inserter() at source / destination with correct direction
    →  verify_connection() (check belt carries items)

KEY RULES:
 1. Transport belts are directional; each segment must face the flow direction.
 2. Inserters face TOWARD their destination (rotation matters).
 3. Burner inserters need fuel; electric inserters need power.
 4. Always place the belt path BEFORE placing inserters.
 5. Underground belts let you cross gaps (max 4 tiles underground).
"""

# ─── Example 1: Connect a Miner to a Furnace with a Belt ─────────────────────
BELT_MINER_TO_FURNACE = """
# Goal: connect a burner mining drill output to a stone furnace input using belts.
# Assumes drill is at DRILL_POS outputting NORTH and furnace is 5 tiles north.

from factorio_learning_environment.entities import Prototype, Direction, Position

# --- Locate existing drill and furnace (adjust to your layout) ---
drills   = get_entities(Prototype.BurnerMiningDrill)
furnaces = get_entities(Prototype.StoneFurnace)

if not drills:
    print("ERROR: no burner mining drill found. Place one first.")
elif not furnaces:
    print("ERROR: no stone furnace found. Place one first.")
else:
    drill   = drills[0]
    furnace = furnaces[0]

    # Drill output is on its NORTH face (one tile above drill centre)
    drill_output_pos   = Position(x=drill.position.x, y=drill.position.y - 1)
    # Furnace input is on its SOUTH face (one tile below furnace centre)
    furnace_input_pos  = Position(x=furnace.position.x, y=furnace.position.y + 1)

    # Ensure we have belts
    belt_count = abs(int(furnace_input_pos.y - drill_output_pos.y)) + 1
    inv = inspect_inventory()
    if inv.get('transport-belt', 0) < belt_count:
        craft_item(Prototype.TransportBelt, quantity=belt_count + 4)

    # Place belt tiles from drill output northward to furnace input
    current_y = drill_output_pos.y
    while current_y >= furnace_input_pos.y:
        belt_pos = Position(x=drill_output_pos.x, y=current_y)
        try:
            place_entity(Prototype.TransportBelt, belt_pos, Direction.NORTH)
        except Exception as e:
            print(f"Belt at {belt_pos}: {e}")
        current_y -= 1

    print(f"Belt line placed from {drill_output_pos} to {furnace_input_pos}")
"""

# ─── Example 2: Place Inserters to Load/Unload Furnace ───────────────────────
ADD_INSERTERS = """
# Goal: add a burner inserter on each side of a stone furnace:
#  - one inserter to LOAD iron ore from a belt into the furnace
#  - one inserter to UNLOAD iron plates from furnace onto an output belt

from factorio_learning_environment.entities import Prototype, Direction, Position

furnaces = get_entities(Prototype.StoneFurnace)
if not furnaces:
    print("ERROR: place a stone furnace first.")
else:
    furnace = furnaces[0]
    fx, fy  = furnace.position.x, furnace.position.y

    inv = inspect_inventory()
    inserters_needed = 2
    if inv.get('burner-inserter', 0) < inserters_needed:
        craft_item(Prototype.BurnerInserter, quantity=inserters_needed)

    # Input inserter: sits on SOUTH side of furnace, points NORTH (toward furnace)
    input_inserter_pos = Position(x=fx, y=fy + 2)
    in_ins = place_entity(Prototype.BurnerInserter, input_inserter_pos, Direction.NORTH)
    insert_item(in_ins, Prototype.Coal, quantity=5)     # fuel the inserter itself
    print(f"Input inserter placed at {in_ins.position} facing NORTH")

    # Output inserter: sits on NORTH side, points SOUTH (picks from furnace)
    # Wait — inserter direction = the direction it THROWS items
    # So output inserter throws north → sits on north side of furnace facing NORTH
    output_inserter_pos = Position(x=fx, y=fy - 2)
    out_ins = place_entity(Prototype.BurnerInserter, output_inserter_pos, Direction.SOUTH)
    insert_item(out_ins, Prototype.Coal, quantity=5)
    print(f"Output inserter placed at {out_ins.position} facing SOUTH")

    print("Inserters placed and fuelled.")
"""

# ─── Example 3: Connect Steam Power (Boiler → Steam Engine) ──────────────────
BUILD_STEAM_POWER = """
# Goal: build a minimal steam power setup: offshore pump → boiler → steam engine.
# This provides ~900 kW, enough for ~18 electric mining drills.

from factorio_learning_environment.entities import Prototype, Direction, Position

# Craft required entities if missing
inv = inspect_inventory()
needed = {
    'offshore-pump': 1,
    'boiler': 1,
    'steam-engine': 1,
    'pipe': 4,
    'small-electric-pole': 2,
}
for item, qty in needed.items():
    prototype = getattr(Prototype, item.replace('-', '_').title().replace('_', ''), None)
    if prototype and inv.get(item, 0) < qty:
        try:
            craft_item(prototype, quantity=qty)
        except Exception as e:
            print(f"Could not craft {item}: {e}")

# Find water
water_tiles = get_resource_patches('water', radius=50)
if not water_tiles:
    print("ERROR: no water within 50 tiles — cannot build steam power.")
else:
    water_pos = water_tiles[0].position

    # Offshore pump on water edge, pumping EAST
    pump_pos = Position(x=water_pos.x + 1, y=water_pos.y)
    pump = place_entity(Prototype.OffshorePump, pump_pos, Direction.EAST)

    # Boiler 3 tiles east of pump
    boiler_pos = Position(x=pump_pos.x + 3, y=pump_pos.y)
    boiler = place_entity(Prototype.Boiler, boiler_pos, Direction.EAST)
    insert_item(boiler, Prototype.Coal, quantity=20)

    # Steam engine 4 tiles east of boiler
    engine_pos = Position(x=boiler_pos.x + 4, y=boiler_pos.y)
    engine = place_entity(Prototype.SteamEngine, engine_pos, Direction.EAST)

    # Connect pump → boiler and boiler → engine with pipes
    for pipe_x in [pump_pos.x + 1, pump_pos.x + 2]:
        place_entity(Prototype.Pipe, Position(x=pipe_x, y=pump_pos.y), Direction.EAST)
    for pipe_x in [boiler_pos.x + 1, boiler_pos.x + 2, boiler_pos.x + 3]:
        place_entity(Prototype.Pipe, Position(x=pipe_x, y=boiler_pos.y), Direction.EAST)

    print(f"Steam power setup: pump@{pump.position} → boiler@{boiler.position} → engine@{engine.position}")
    print("Wait ~10 s for pressure to build before drawing power.")
"""

ALL_EXAMPLES = {
    "belt_miner_to_furnace": BELT_MINER_TO_FURNACE,
    "add_inserters": ADD_INSERTERS,
    "build_steam_power": BUILD_STEAM_POWER,
}
