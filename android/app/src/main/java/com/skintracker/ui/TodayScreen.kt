package com.skintracker.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AlarmOff
import androidx.compose.material.icons.filled.DoneAll
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import com.skintracker.data.RoutineWithSteps
import com.skintracker.data.Step
import com.skintracker.schedule.Repeat
import java.time.LocalTime
import java.time.format.DateTimeFormatter

private val timeFormat: DateTimeFormatter = DateTimeFormatter.ofPattern("h:mm a")

@Composable
fun TodayScreen(
    routines: List<RoutineWithSteps>,
    done: Set<Long>,
    onToggle: (Step, Boolean) -> Unit,
    onMarkAll: (RoutineWithSteps) -> Unit,
    onClear: (RoutineWithSteps) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (routines.isEmpty()) {
        EmptyState(
            title = "No routines yet",
            body = "Add one on the Routines tab — give it a time, pick the days, " +
                "and list the products you use.",
            modifier = modifier,
        )
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        items(routines, key = { it.routine.id }) { rws ->
            RoutineCard(rws, done, onToggle, onMarkAll, onClear)
        }
        item { Spacer(Modifier.height(72.dp)) }
    }
}

@Composable
private fun RoutineCard(
    rws: RoutineWithSteps,
    done: Set<Long>,
    onToggle: (Step, Boolean) -> Unit,
    onMarkAll: (RoutineWithSteps) -> Unit,
    onClear: (RoutineWithSteps) -> Unit,
) {
    val steps = rws.orderedSteps
    val doneCount = steps.count { it.id in done }
    val allDone = steps.isNotEmpty() && doneCount == steps.size

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(rws.routine.name, style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold)
                    Text(
                        LocalTime.of(rws.routine.hour, rws.routine.minute).format(timeFormat) +
                            " · " + Repeat.describe(rws.routine.repeatMask),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (!rws.routine.enabled) {
                    AssistChip(
                        onClick = {},
                        enabled = false,
                        leadingIcon = { Icon(Icons.Default.AlarmOff, null, Modifier.size(16.dp)) },
                        label = { Text("Off") },
                    )
                }
            }

            if (steps.isEmpty()) {
                Spacer(Modifier.height(10.dp))
                Text(
                    "No products in this routine yet.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                return@Column
            }

            Spacer(Modifier.height(12.dp))
            LinearProgressIndicator(
                progress = { doneCount.toFloat() / steps.size },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                if (allDone) "All done for today ✨" else "$doneCount of ${steps.size} done",
                style = MaterialTheme.typography.labelMedium,
                color = if (allDone) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(6.dp))
            steps.forEachIndexed { index, step ->
                val isDone = step.id in done
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Checkbox(checked = isDone, onCheckedChange = { onToggle(step, it) })
                    Text(
                        "${index + 1}. ${step.name}",
                        style = MaterialTheme.typography.bodyLarge,
                        textDecoration = if (isDone) TextDecoration.LineThrough else null,
                        color = if (isDone) MaterialTheme.colorScheme.onSurfaceVariant
                                else MaterialTheme.colorScheme.onSurface,
                    )
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { onMarkAll(rws) }, enabled = !allDone) {
                    Icon(Icons.Default.DoneAll, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Mark all")
                }
                TextButton(onClick = { onClear(rws) }, enabled = doneCount > 0) {
                    Icon(Icons.Default.Refresh, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Reset")
                }
            }
        }
    }
}

@Composable
fun EmptyState(title: String, body: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(
            body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}
