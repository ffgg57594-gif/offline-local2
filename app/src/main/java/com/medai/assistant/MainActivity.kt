package com.medai.assistant

import android.content.res.Configuration
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.lifecycle.lifecycleScope
import com.medai.assistant.data.AndroidChunkRepository
import com.medai.assistant.data.AssetInstaller
import com.medai.assistant.data.Chunk
import com.medai.assistant.data.ChunkRepository
import com.medai.assistant.data.ContextAssetSource
import com.medai.assistant.data.InstallState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class MainActivity : ComponentActivity() {

    private lateinit var installer: AssetInstaller
    private var repository by mutableStateOf<ChunkRepository?>(null)
    private var chunkCount by mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        val assetSource = ContextAssetSource(applicationContext)
        installer = AssetInstaller(targetBaseDir = filesDir, assetSource = assetSource)

        lifecycleScope.launch {
            try {
                val installedDir = installer.install()
                val dbFile = File(installedDir, "books_knowledge.db")
                if (dbFile.exists()) {
                    val repo = AndroidChunkRepository(dbFile)
                    val count = withContext(Dispatchers.IO) { repo.count() }
                    chunkCount = count
                    repository = repo
                }
            } catch (e: Exception) {
                // InstallState.Failed is already set by installer
            }
        }

        setContent {
            val isDark = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
                    Configuration.UI_MODE_NIGHT_YES
            val colorScheme = if (isDark) darkColorScheme() else lightColorScheme()

            MaterialTheme(colorScheme = colorScheme) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    val installState by installer.installState.collectAsState()
                    DebugScreen(
                        installState = installState,
                        chunkCount = chunkCount,
                        repository = repository
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugScreen(
    installState: InstallState,
    chunkCount: Int,
    repository: ChunkRepository?
) {
    var chunkIdInput by remember { mutableStateOf("61") }
    var loadedChunk by remember { mutableStateOf<Chunk?>(null) }
    var queryError by remember { mutableStateOf<String?>(null) }
    val coroutineScope = rememberCoroutineScope()

    // Auto load chunk 61 once ready
    LaunchedEffect(repository) {
        if (repository != null) {
            withContext(Dispatchers.IO) {
                loadedChunk = repository.getById(61)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("MedAI Debug / K1") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                    titleContentColor = MaterialTheme.colorScheme.onPrimaryContainer
                )
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 1. Install Progress Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Asset Install State", style = MaterialTheme.typography.titleMedium)

                    when (val state = installState) {
                        is InstallState.Idle -> {
                            Text("Preparing...", style = MaterialTheme.typography.bodyMedium)
                        }
                        is InstallState.Copying -> {
                            Text(
                                "Copying: ${state.fileName}",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            val progress = if (state.totalBytes > 0) {
                                state.doneBytes.toFloat() / state.totalBytes.toFloat()
                            } else 0f
                            LinearProgressIndicator(
                                progress = { progress },
                                modifier = Modifier.fillMaxWidth()
                            )
                            Text(
                                "${state.doneBytes / 1024} KB / ${state.totalBytes / 1024} KB (${(progress * 100).toInt()}%)",
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                        is InstallState.Ready -> {
                            Text("Ready (All assets verified)", color = MaterialTheme.colorScheme.primary)
                            Text("Directory: ${state.dir.name}", style = MaterialTheme.typography.bodySmall)
                        }
                        is InstallState.Failed -> {
                            Text("Error: ${state.message}", color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }

            // 2. Database Stats Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Books Knowledge DB", style = MaterialTheme.typography.titleMedium)
                    if (repository != null) {
                        Text("Total Chunks: $chunkCount", style = MaterialTheme.typography.bodyLarge)
                    } else {
                        Text("Awaiting database installation...", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }

            // 3. Chunk Inspector Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Chunk Inspector", style = MaterialTheme.typography.titleMedium)

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = chunkIdInput,
                            onValueChange = { chunkIdInput = it },
                            label = { Text("Chunk ID (1..1185)") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                        Button(
                            onClick = {
                                val id = chunkIdInput.trim().toIntOrNull()
                                if (id == null) {
                                    queryError = "Please enter a valid number"
                                    loadedChunk = null
                                } else if (repository == null) {
                                    queryError = "Database not ready yet"
                                } else {
                                    queryError = null
                                    coroutineScope.launch {
                                        loadedChunk = withContext(Dispatchers.IO) {
                                            repository.getById(id)
                                        }
                                        if (loadedChunk == null) {
                                            queryError = "Chunk $id not found"
                                        }
                                    }
                                }
                            },
                            enabled = repository != null
                        ) {
                            Text("Load")
                        }
                    }

                    if (queryError != null) {
                        Text(queryError!!, color = MaterialTheme.colorScheme.error)
                    }

                    loadedChunk?.let { chunk ->
                        HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
                        Text("Chunk #${chunk.id}", style = MaterialTheme.typography.titleSmall)
                        Text("Book: ${chunk.bookName}", style = MaterialTheme.typography.bodySmall)
                        Text("Page: ${chunk.page}", style = MaterialTheme.typography.bodyMedium)
                        if (chunk.section.isNotBlank()) {
                            Text("Section: ${chunk.section}", style = MaterialTheme.typography.bodySmall)
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = chunk.text,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 4.dp)
                        )
                    }
                }
            }
        }
    }
}
