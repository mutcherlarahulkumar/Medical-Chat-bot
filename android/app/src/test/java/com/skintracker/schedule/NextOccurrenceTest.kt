package com.skintracker.schedule

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.DayOfWeek
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * The scheduling maths runs on a plain JVM — no emulator needed:
 *
 *     ./gradlew :app:testDebugUnitTest
 */
class NextOccurrenceTest {

    private val london = ZoneId.of("Europe/London")
    private val ny = ZoneId.of("America/New_York")
    private val kolkata = ZoneId.of("Asia/Kolkata")

    /** Wednesday 2026-09-16, 09:00 local. */
    private fun wed(zone: ZoneId = london) = ZonedDateTime.of(2026, 9, 16, 9, 0, 0, 0, zone)

    @Test fun `once later today`() {
        assertEquals("2026-09-16T22:00",
            nextOccurrence(22, 0, Repeat.ONCE, wed())!!.toLocalDateTime().toString())
    }

    @Test fun `once already passed rolls to tomorrow`() {
        assertEquals("2026-09-17T07:30",
            nextOccurrence(7, 30, Repeat.ONCE, wed())!!.toLocalDateTime().toString())
    }

    @Test fun `a time equal to now counts as passed`() {
        // Guards the reschedule-after-fire loop: an alarm must never re-book
        // itself against the very instant it just fired.
        assertEquals("2026-09-17T09:00",
            nextOccurrence(9, 0, Repeat.ONCE, wed())!!.toLocalDateTime().toString())
    }

    @Test fun `daily later today`() {
        assertEquals("2026-09-16T21:15",
            nextOccurrence(21, 15, Repeat.EVERY_DAY, wed())!!.toLocalDateTime().toString())
    }

    @Test fun `daily already passed rolls to tomorrow`() {
        assertEquals("2026-09-17T08:00",
            nextOccurrence(8, 0, Repeat.EVERY_DAY, wed())!!.toLocalDateTime().toString())
    }

    @Test fun `weekday mask skips the weekend`() {
        val fridayLate = ZonedDateTime.of(2026, 9, 18, 23, 0, 0, 0, london)
        val n = nextOccurrence(7, 0, Repeat.WEEKDAYS, fridayLate)!!
        assertEquals(DayOfWeek.MONDAY, n.dayOfWeek)
        assertEquals("2026-09-21T07:00", n.toLocalDateTime().toString())
    }

    @Test fun `weekend mask from midweek`() {
        val n = nextOccurrence(10, 0, Repeat.WEEKENDS, wed())!!
        assertEquals(DayOfWeek.SATURDAY, n.dayOfWeek)
        assertEquals("2026-09-19T10:00", n.toLocalDateTime().toString())
    }

    @Test fun `a single weekday wraps a whole week`() {
        val onlyWed = Repeat.bit(DayOfWeek.WEDNESDAY)
        val n = nextOccurrence(8, 0, onlyWed, wed())!!
        assertEquals("2026-09-23T08:00", n.toLocalDateTime().toString())
    }

    @Test fun `a mask with no days never fires`() {
        assertNull(nextOccurrence(8, 0, 1 shl 7, wed()))
    }

    @Test fun `every result is strictly in the future and keeps its clock time`() {
        val now = wed()
        for (h in 0..23) for (m in listOf(0, 30, 59)) {
            for (mask in listOf(Repeat.ONCE, Repeat.EVERY_DAY, Repeat.WEEKDAYS, Repeat.WEEKENDS)) {
                val n = nextOccurrence(h, m, mask, now)!!
                assertTrue("h=$h m=$m mask=$mask gave $n", n.isAfter(now))
                assertEquals(h.toLong(), n.hour.toLong())
                assertEquals(m.toLong(), n.minute.toLong())
            }
        }
    }

    @Test fun `spring forward gap does not drop the reminder`() {
        // London 2026-03-29: 01:00 jumps to 02:00, so 01:30 does not exist.
        val before = ZonedDateTime.of(2026, 3, 28, 12, 0, 0, 0, london)
        val n = nextOccurrence(1, 30, Repeat.EVERY_DAY, before)!!
        assertEquals(29, n.dayOfMonth.toLong())   // still fires that day
        assertEquals(2, n.hour.toLong())          // shifted past the gap
    }

    @Test fun `autumn fall back fires once`() {
        // London 2026-10-25: 02:00 falls back to 01:00, so 01:30 happens twice.
        val before = ZonedDateTime.of(2026, 10, 24, 12, 0, 0, 0, london)
        val n = nextOccurrence(1, 30, Repeat.EVERY_DAY, before)!!
        assertEquals(25, n.dayOfMonth.toLong())
        assertEquals(1, n.hour.toLong())
        assertEquals(30, n.minute.toLong())
    }

    @Test fun `new york spring gap`() {
        val before = ZonedDateTime.of(2026, 3, 7, 12, 0, 0, 0, ny)
        val n = nextOccurrence(2, 30, Repeat.EVERY_DAY, before)!!
        assertEquals(8, n.dayOfMonth.toLong())
        assertEquals(3, n.hour.toLong())          // 02:30 skipped
    }

    @Test fun `half hour offset timezone`() {
        val now = ZonedDateTime.of(2026, 9, 16, 9, 0, 0, 0, kolkata)
        val n = nextOccurrence(22, 30, Repeat.EVERY_DAY, now)!!
        assertEquals("2026-09-16T22:30", n.toLocalDateTime().toString())
        assertEquals(kolkata, n.zone)
    }

    @Test fun `describe reads like a human wrote it`() {
        assertEquals("Once", Repeat.describe(Repeat.ONCE))
        assertEquals("Every day", Repeat.describe(Repeat.EVERY_DAY))
        assertEquals("Weekdays", Repeat.describe(Repeat.WEEKDAYS))
        assertEquals("Weekends", Repeat.describe(Repeat.WEEKENDS))
        val mwf = Repeat.bit(DayOfWeek.MONDAY) or Repeat.bit(DayOfWeek.WEDNESDAY) or
            Repeat.bit(DayOfWeek.FRIDAY)
        assertEquals("Mon, Wed, Fri", Repeat.describe(mwf))
    }

    @Test fun `toggling a day round trips`() {
        var m = Repeat.ONCE
        m = Repeat.toggle(m, DayOfWeek.TUESDAY)
        assertTrue(Repeat.includes(m, DayOfWeek.TUESDAY))
        assertEquals(Repeat.ONCE.toLong(), Repeat.toggle(m, DayOfWeek.TUESDAY).toLong())
    }

    @Test fun `impossible clock times are rejected`() {
        listOf(-1 to 0, 24 to 0, 0 to -1, 0 to 60).forEach { (h, m) ->
            try {
                nextOccurrence(h, m, Repeat.EVERY_DAY, wed())
                throw AssertionError("accepted $h:$m")
            } catch (expected: IllegalArgumentException) {
                // good
            }
        }
    }

    @Test fun `firing repeatedly advances one period at a time`() {
        val mask = Repeat.bit(DayOfWeek.MONDAY) or Repeat.bit(DayOfWeek.THURSDAY)
        var t = nextOccurrence(7, 0, mask, wed())!!
        assertEquals(DayOfWeek.THURSDAY, t.dayOfWeek)
        t = nextOccurrence(7, 0, mask, t)!!
        assertEquals(DayOfWeek.MONDAY, t.dayOfWeek)
        t = nextOccurrence(7, 0, mask, t)!!
        assertEquals(DayOfWeek.THURSDAY, t.dayOfWeek)
    }
}
