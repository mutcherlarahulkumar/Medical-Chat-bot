package com.skintracker.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.skintracker.data.Routine
import com.skintracker.data.RoutineWithSteps
import com.skintracker.data.Step
import com.skintracker.schedule.Repeat
import java.time.DayOfWeek
import java.time.LocalTime
import java.time.format.DateTimeFormatter

private val timeFormat: DateTimeFormatter = DateTimeFormatter.ofPattern("h:mm a")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EditRoutineScreen(
    existing: RoutineWithSteps?,
    onSave: (Routine) -> Unit,
    onDelete: (Routine) -> Unit,
    onAddStep: (String) -> Unit,
    onDeleteStep: (Step) -> Unit,
    onMoveStep: (Int, Int) -> Unit,
    onBack: () -> Unit,
) {
    val routine = existing?.routine
    var name by rememberSaveable { mutableStateOf(routine?.name ?: "") }
    var hour by rememberSaveable { mutableIntStateOf(routine?.hour ?: 8) }
    var minute by rememberSaveable { mutableIntStateOf(routine?.minute ?: 0) }
    var mask by rememberSaveable { mutableIntStateOf(routine?.repeatMask ?: Repeat.EVERY_DAY) }
    var newStep by rememberSaveable { mutableStateOf("") }
    var showTimePicker by rememberSaveable { mutableStateOf(false) }
    var confirmDelete by rememberSaveable { mutableStateOf(false) }

    val steps = existing?.orderedSteps.orEmpty()
    val canSave = name.isNotBlank()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (routine == null) "New routine" else "Edit routine") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (routine != null) {
                        IconButton(onClick = { confirmDelete = true }) {
                            Icon(Icons.Default.Delete, contentDescription = "Delete routine")
                        }
                    }
                    TextButton(
                        enabled = canSave,
                        onClick = {
                            onSave(
                                (routine ?: Routine(name = "", hour = hour, minute = minute)).copy(
                                    name = name.trim(),
                                    hour = hour,
                                    minute = minute,
                                    repeatMask = mask,
                                )
                            )
                        },
                    ) { Text("Save") }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            Modifier.padding(padding).fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it.take(40) },
                    label = { Text("Routine name") },
                    placeholder = { Text("Morning") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Reminder time", style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(6.dp))
                        TextButton(onClick = { showTimePicker = true }) {
                            Text(
                                LocalTime.of(hour, minute).format(timeFormat),
                                style = MaterialTheme.typography.headlineMedium,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }

            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Repeats", style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            DayOfWeek.entries.forEach { day ->
                                val on = Repeat.includes(mask, day)
                                FilterChip(
                                    selected = on,
                                    onClick = { mask = Repeat.toggle(mask, day) },
                                    label = { Text(day.name.take(1)) },
                                )
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { mask = Repeat.EVERY_DAY }) { Text("Every day") }
                            TextButton(onClick = { mask = Repeat.WEEKDAYS }) { Text("Weekdays") }
                            TextButton(onClick = { mask = Repeat.ONCE }) { Text("Once") }
                        }
                        Text(
                            Repeat.describe(mask),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            item {
                Text("Products", style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold)
                Text(
                    if (routine == null) "Save the routine first, then add products."
                    else "In the order you apply them.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            itemsIndexed(steps, key = { _, s -> s.id }) { index, step ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Text("${index + 1}", style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Text(step.name, Modifier.weight(1f),
                            style = MaterialTheme.typography.bodyLarge)
                        IconButton(onClick = { onMoveStep(index, index - 1) },
                            enabled = index > 0) {
                            Icon(Icons.Default.ArrowUpward, "Move up", Modifier.size(20.dp))
                        }
                        IconButton(onClick = { onMoveStep(index, index + 1) },
                            enabled = index < steps.lastIndex) {
                            Icon(Icons.Default.ArrowDownward, "Move down", Modifier.size(20.dp))
                        }
                        IconButton(onClick = { onDeleteStep(step) }) {
                            Icon(Icons.Default.Close, "Remove ${step.name}", Modifier.size(20.dp))
                        }
                    }
                }
            }

            if (routine != null) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = newStep,
                            onValueChange = { newStep = it.take(60) },
                            label = { Text("Add a product") },
                            placeholder = { Text("Niacinamide 10%") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        Button(
                            onClick = { onAddStep(newStep); newStep = "" },
                            enabled = newStep.isNotBlank(),
                        ) { Text("Add") }
                    }
                }
            }

            item { Spacer(Modifier.height(40.dp)) }
        }
    }

    if (showTimePicker) {
        val state = rememberTimePickerState(initialHour = hour, initialMinute = minute, is24Hour = false)
        AlertDialog(
            onDismissRequest = { showTimePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    hour = state.hour; minute = state.minute; showTimePicker = false
                }) { Text("OK") }
            },
            dismissButton = {
                TextButton(onClick = { showTimePicker = false }) { Text("Cancel") }
            },
            text = { TimePicker(state = state) },
        )
    }

    if (confirmDelete && routine != null) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete \"${routine.name}\"?") },
            text = { Text("Its products and reminder go too. Your past check-offs stay.") },
            confirmButton = {
                TextButton(onClick = { confirmDelete = false; onDelete(routine) }) {
                    Text("Delete")
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = false }) { Text("Cancel") }
            },
        )
    }
}
