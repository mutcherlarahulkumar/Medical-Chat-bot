# Room generates implementations reflectively at build time; nothing extra needed.
# Keep the alarm/boot receivers, which are only referenced from the manifest.
-keep class com.skintracker.schedule.AlarmReceiver { *; }
-keep class com.skintracker.schedule.BootReceiver { *; }
