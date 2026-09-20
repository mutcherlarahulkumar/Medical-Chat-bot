package com.skintracker

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.skintracker.schedule.AlarmScheduler
import com.skintracker.schedule.Notifications
import com.skintracker.ui.AppViewModel
import com.skintracker.ui.EditRoutineScreen
import com.skintracker.ui.RoutinesScreen
import com.skintracker.ui.TodayScreen
import com.skintracker.ui.theme.SkinTrackerTheme

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifications.ensureChannel(this)

        // Opened from a notification? Jump straight to that routine's checklist.
        val fromNotification = intent?.getLongExtra(Notifications.EXTRA_ROUTINE_ID, -1L) ?: -1L

        setContent {
            SkinTrackerTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    SkinTrackerApp(openedRoutineId = fromNotification)
                }
            }
        }
    }
}

private enum class Tab { Today, Routines }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SkinTrackerApp(openedRoutineId: Long = -1L, vm: AppViewModel = viewModel()) {
    val routines by vm.routines.collectAsState()
    val done by vm.doneToday.collectAsState()
    val context = LocalContext.current

    var tab by rememberSaveable { mutableStateOf(Tab.Today) }
    // -1 = not editing, 0 = creating a new routine, >0 = editing that routine.
    var editingId by rememberSaveable { mutableLongStateOf(-1L) }

    // Alarms are dropped by the OS on reboot; re-book them whenever we start.
    LaunchedEffect(Unit) { vm.rescheduleAll() }

    // Android 13+ needs the user's say-so before we can post a reminder at all.
    val askNotifications = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* if denied, the banner below keeps explaining why */ }

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    if (editingId >= 0L) {
        val existing = routines.firstOrNull { it.routine.id == editingId }
        EditRoutineScreen(
            existing = existing,
            onSave = { r -> vm.saveRoutine(r) { id -> editingId = id } },
            onDelete = { r -> vm.deleteRoutine(r); editingId = -1L },
            onAddStep = { name -> vm.addStep(editingId, name) },
            onDeleteStep = { step -> vm.deleteStep(step) },
            onMoveStep = { from, to -> existing?.let { vm.moveStep(it.orderedSteps, from, to) } },
            onBack = { editingId = -1L },
        )
        return
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Skin Tracker") }) },
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = tab == Tab.Today,
                    onClick = { tab = Tab.Today },
                    icon = { Icon(Icons.Default.CheckCircle, null) },
                    label = { Text("Today") },
                )
                NavigationBarItem(
                    selected = tab == Tab.Routines,
                    onClick = { tab = Tab.Routines },
                    icon = { Icon(Icons.Default.Schedule, null) },
                    label = { Text("Routines") },
                )
            }
        },
        floatingActionButton = {
            if (tab == Tab.Routines) {
                FloatingActionButton(onClick = { editingId = 0L }) {
                    Icon(Icons.Default.Add, contentDescription = "New routine")
                }
            }
        },
    ) { padding ->
        Column(Modifier.padding(padding)) {
            if (!AlarmScheduler.canScheduleExact(context)) {
                ExactAlarmBanner()
            }
            when (tab) {
                Tab.Today -> TodayScreen(
                    routines = routines,
                    done = done,
                    onToggle = vm::toggleStep,
                    onMarkAll = vm::markAllDone,
                    onClear = vm::clearRoutine,
                )
                Tab.Routines -> RoutinesScreen(
                    routines = routines,
                    onEdit = { editingId = it },
                    onToggleEnabled = vm::setEnabled,
                )
            }
        }
    }

    // Arriving from a notification lands you on the checklist.
    LaunchedEffect(openedRoutineId) {
        if (openedRoutineId > 0) tab = Tab.Today
    }
}

@Composable
private fun ExactAlarmBanner() {
    val context = LocalContext.current
    Card(
        Modifier.fillMaxWidth().padding(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text("Reminders may arrive late", style = MaterialTheme.typography.titleSmall)
            Text(
                "Android is holding back exact alarms for this app, so a reminder " +
                    "can slip by up to 10 minutes.",
                style = MaterialTheme.typography.bodySmall,
            )
            TextButton(onClick = {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    context.startActivity(
                        Intent(
                            Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                            Uri.parse("package:${context.packageName}"),
                        )
                    )
                }
            }) { Text("Allow exact alarms") }
        }
    }
}
