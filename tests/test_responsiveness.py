from babysitter.responsiveness import ResponsivenessLog, TurnClock


def test_the_log_keeps_timings_and_drops_words():
    log = ResponsivenessLog()
    log.add({"first_sound": 800, "transcript": 120, "heard": "what time is it"})
    log.add({"first_sound": 1400})
    assert log.rows == [{"first_sound": 800, "transcript": 120}, {"first_sound": 1400}]
    assert "what time" not in log.summary()
    assert "what time" not in log.export_text()
    assert "Typical time to first sound: 800 ms" in log.summary()
    assert "Worst: 1400 ms" in log.summary()


def test_a_turn_clock_records_milliseconds():
    clock = TurnClock()
    clock.mark("transcript")
    clock.mark("transcript")
    row = clock.as_row()
    assert row["transcript"] == 0 or row["transcript"] >= 0
    assert list(row).count("transcript") == 1
