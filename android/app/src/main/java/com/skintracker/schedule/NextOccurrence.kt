package com.skintracker.schedule

import java.time.DayOfWeek
import java.time.ZonedDateTime

/**
 * Pure scheduling maths — no Android imports, so it is unit-testable on a plain JVM.
 *
 * A repeat is a 7-bit mask: Monday is bit 0 ... Sunday is bit 6. A mask of
 * [Repeat.ONCE] means the reminder fires once, at the next occurrence of that
 * clock time, and is then switched off.
 */
object Repeat {
    const val ONCE = 0
    const val EVERY_DAY = 0b1111111
    const val WEEKDAYS = 0b0011111      // Mon-Fri
    const val WEEKENDS = 0b1100000      // Sat-Sun

    fun bit(day: DayOfWeek): Int = 1 shl (day.value - 1)

    fun includes(mask: Int, day: DayOfWeek): Boolean = (mask and bit(day)) != 0

    fun toggle(mask: Int, day: DayOfWeek): Int = mask xor bit(day)

    /** "Every day", "Weekdays", "Mon, Wed, Fri", "Once". */
    fun describe(mask: Int): String = when (mask) {
        ONCE -> "Once"
        EVERY_DAY -> "Every day"
        WEEKDAYS -> "Weekdays"
        WEEKENDS -> "Weekends"
        else -> DayOfWeek.entries
            .filter { includes(mask, it) }
            .joinToString(", ") { it.name.lowercase().replaceFirstChar(Char::uppercase).take(3) }
    }
}

/**
 * The next moment this reminder should fire, strictly after [from].
 *
 * Boundary behaviour that matters in practice:
 * - A time that has already passed today rolls to the next matching day.
 * - A time exactly equal to [from] counts as passed, so an alarm never
 *   re-fires against the instant it just went off.
 * - On the day a clock jumps forward, a wall-clock time inside the skipped
 *   hour does not exist; java.time shifts it forward by the gap, so the
 *   reminder still fires that day rather than being silently dropped.
 *
 * Returns null only when [mask] selects no days at all and is not [Repeat.ONCE],
 * which callers should treat as "never fires".
 */
fun nextOccurrence(
    hour: Int,
    minute: Int,
    mask: Int,
    from: ZonedDateTime,
): ZonedDateTime? {
    require(hour in 0..23) { "hour must be 0..23, was $hour" }
    require(minute in 0..59) { "minute must be 0..59, was $minute" }

    if (mask == Repeat.ONCE) {
        val today = from.toLocalDate().atTime(hour, minute).atZone(from.zone)
        return if (today.isAfter(from)) today
        else from.toLocalDate().plusDays(1).atTime(hour, minute).atZone(from.zone)
    }

    if (mask and Repeat.EVERY_DAY == 0) return null

    // Look at most a week ahead; one of those days must match.
    for (offset in 0..7) {
        val date = from.toLocalDate().plusDays(offset.toLong())
        if (!Repeat.includes(mask, date.dayOfWeek)) continue
        val candidate = date.atTime(hour, minute).atZone(from.zone)
        if (candidate.isAfter(from)) return candidate
    }
    return null
}
