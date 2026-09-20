# 🌸 Skin Tracker — Android

A native Kotlin app for actually *doing* your skincare routine: set the times,
get an alarm, tick products off a checklist so you know nothing was missed.

**No photos. No accounts. No network.** The app has no `INTERNET` permission at
all — everything lives in a local SQLite database on the phone.

## What it does

- **Routines** — a name, a time, and the days it repeats. "Morning 07:00, every
  day." "Retinol 22:00, Mon/Wed/Fri."
- **Products in order** — each routine holds the products you apply, numbered in
  application order, reorderable with ↑ / ↓.
- **Alarms** — an exact alarm at the set time, surviving Doze and reboots.
- **Checklist** — the notification opens a checklist for that routine. Tick each
  product; a progress bar shows how much is left. It resets each day, and
  yesterday's ticks are kept.
- **Repeat options** — every day, weekdays, weekends, any set of days, or once.

## Build it

Needs [Android Studio](https://developer.android.com/studio) (which brings the
Android SDK) and JDK 17+.

```bash
# from this directory
./gradlew assembleDebug        # → app/build/outputs/apk/debug/app-debug.apk
./gradlew installDebug         # straight onto a connected phone
```

Or open the `android/` folder in Android Studio and hit **Run ▶**.

Run the scheduling tests without an emulator:

```bash
./gradlew :app:testDebugUnitTest
```

> The Gradle wrapper JAR is not committed. Android Studio regenerates it on
> first open, or run `gradle wrapper` once if you have Gradle installed.

## How it's put together

| Path | What it is |
|---|---|
| `schedule/NextOccurrence.kt` | When does this reminder fire next? Pure Kotlin, no Android — hence unit-testable |
| `schedule/AlarmScheduler.kt` | Books and cancels `AlarmManager` alarms |
| `schedule/AlarmReceiver.kt` | Fires → notify → book the next one |
| `schedule/BootReceiver.kt` | Re-books everything after reboot / clock change |
| `data/` | Room: `Routine`, `Step` (a product), `CheckOff` (a tick) |
| `ui/` | Compose Material 3, pink theme, light and dark |

### Why one-shot alarms instead of a repeating one

Android's repeating alarms are inexact and get deferred in Doze, which is fatal
for a reminder you rely on. So each alarm is a single exact alarm, and the
receiver books the next occurrence as soon as it fires. The OS drops all pending
alarms on reboot, so `BootReceiver` re-books them — it also listens for clock and
timezone changes, which invalidate times already computed.

### Permissions, and why

| Permission | Why |
|---|---|
| `POST_NOTIFICATIONS` | Requested at runtime on Android 13+. Without it, no reminders |
| `USE_EXACT_ALARM` | A skincare reminder is a user-set alarm, which is what this is for |
| `SCHEDULE_EXACT_ALARM` | The pre-Android-13 equivalent, capped at `maxSdkVersion=32` |
| `RECEIVE_BOOT_COMPLETED` | Re-book alarms the OS dropped at reboot |

If exact alarms are denied, the app doesn't fail silently: it falls back to a
10-minute window and shows a banner offering to open the right settings page.

## What's tested, and what isn't

**Tested (18 unit tests, all passing):** every branch of the scheduling maths —
times already passed today, weekday and weekend masks, single-day masks wrapping
a full week, a time exactly equal to "now", the repeated fire-then-reschedule
loop, half-hour-offset timezones, and both daylight-saving transitions (a
reminder set inside a spring-forward gap still fires that day rather than being
dropped).

**Not yet run:** the app itself has never been compiled or launched. It was
written in an environment without the Android SDK, so expect to fix a few things
on first build — a Compose or Room API that moved between versions is the most
likely kind. The logic that's hard to get right is the part that's covered.

## Known limitations

- **Midnight rollover while open.** The checklist picks up "today" when the
  screen is first composed. Leave the app open across midnight and it keeps
  showing yesterday until you reopen it.
- **Per-routine notifications only.** Ticking items off is done in the app, not
  from notification action buttons.
- **No history screen.** Past ticks are stored, but nothing renders them yet.
- **One device.** By design — there's no sync, though Android's own backup is
  enabled for the database, so a phone-to-phone transfer keeps your routines.
