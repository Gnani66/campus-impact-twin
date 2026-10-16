"""
AI campus copilot (Phase 13).

The copilot interprets verified campus data and proposes actions.
It never controls sensors, records or actuators: recommendations
leave here as text and `requires_approval=True`, and the only
thing that can turn advice into an authorised action is the Phase
11 approval service, reached by a person.
"""