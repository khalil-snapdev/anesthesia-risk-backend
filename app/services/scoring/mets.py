from app.models.embedded import MetsCapacity


def classify_mets(can_climb_two_flights: bool) -> MetsCapacity:
    """METs functional capacity, per CLAUDE.md's Scoring Logic section.

    <4 METs = poor functional capacity (flag for further workup),
    >=4 METs = adequate. Ability to climb two flights of stairs is the
    standard proxy for the >=4 METs threshold.
    """
    return MetsCapacity.AT_OR_ABOVE_4 if can_climb_two_flights else MetsCapacity.BELOW_4
