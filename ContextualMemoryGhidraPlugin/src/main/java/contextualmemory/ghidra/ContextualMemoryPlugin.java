package contextualmemory.ghidra;

import contextualmemory.ghidra.scan.GhidraProjectScanner;
import contextualmemory.ghidra.scan.ScanMode;
import contextualmemory.ghidra.util.DatabaseNaming;
import docking.ActionContext;
import docking.action.DockingAction;
import docking.action.MenuData;
import ghidra.app.plugin.PluginCategoryNames;
import ghidra.app.plugin.ProgramPlugin;
import ghidra.framework.model.Project;
import ghidra.framework.plugintool.PluginInfo;
import ghidra.framework.plugintool.PluginStatus;
import ghidra.framework.plugintool.PluginTool;
import ghidra.util.Msg;
import ghidra.util.task.Task;
import ghidra.util.task.TaskLauncher;
import ghidra.util.task.TaskMonitor;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

@PluginInfo(
        status = PluginStatus.RELEASED,
        packageName = "Contextual Memory",
        category = PluginCategoryNames.ANALYSIS,
        shortDescription = "Scans Ghidra projects for Contextual Memory",
        description = "Creates and maintains an immutable project-named SQLite database containing " +
                "program and decompiled function data for a Contextual Memory server.")
public final class ContextualMemoryPlugin extends ProgramPlugin {
    private static final String OWNER = "Contextual Memory";

    public ContextualMemoryPlugin(PluginTool tool) {
        super(tool);
        createScanAction("Scan Project", ScanMode.SCAN);
        createScanAction("Update Project Database", ScanMode.UPDATE);
        createScanAction("Rescan Project", ScanMode.RESCAN);
        createClearAction();
    }

    private void createScanAction(String name, ScanMode mode) {
        DockingAction action = new DockingAction(name, OWNER) {
            @Override
            public void actionPerformed(ActionContext context) {
                Project project = tool.getProject();
                if (project == null) {
                    Msg.showWarn(this, tool.getToolFrame(), OWNER, "No Ghidra project is open.");
                    return;
                }
                Path path = databasePath(project);
                Task task = new ProjectScanTask(project, path, mode);
                new TaskLauncher(task, tool.getToolFrame());
            }
        };
        action.setMenuBarData(new MenuData(new String[] { "Tools", OWNER, name }));
        tool.addAction(action);
    }

    private void createClearAction() {
        String name = "Clear Project Database";
        DockingAction action = new DockingAction(name, OWNER) {
            @Override
            public void actionPerformed(ActionContext context) {
                Project project = tool.getProject();
                if (project == null) {
                    Msg.showWarn(this, tool.getToolFrame(), OWNER, "No Ghidra project is open.");
                    return;
                }
                Path path = databasePath(project);
                try {
                    path.toFile().setWritable(true, true);
                    boolean deleted = Files.deleteIfExists(path);
                    Msg.showInfo(this, tool.getToolFrame(), OWNER,
                            deleted ? "Deleted " + path : "No database exists at " + path);
                }
                catch (IOException e) {
                    Msg.showError(this, tool.getToolFrame(), OWNER,
                            "Could not clear project database", e);
                }
            }
        };
        action.setMenuBarData(new MenuData(new String[] { "Tools", OWNER, name }));
        tool.addAction(action);
    }

    private static Path databasePath(Project project) {
        String configured = System.getProperty("contextual.memory.ghidra.databaseDir");
        Path directory = configured == null || configured.isBlank()
                ? Path.of(System.getProperty("user.home"), ".contextual-memory", "ghidra")
                : Path.of(configured);
        String projectName = project.getProjectLocator().getName();
        return directory.resolve(DatabaseNaming.databaseFileName(projectName));
    }

    private final class ProjectScanTask extends Task {
        private final Project project;
        private final Path path;
        private final ScanMode mode;

        ProjectScanTask(Project project, Path path, ScanMode mode) {
            super(modeLabel(mode), true, true, false);
            this.project = project;
            this.path = path;
            this.mode = mode;
        }

        @Override
        public void run(TaskMonitor monitor) {
            GhidraProjectScanner scanner = new GhidraProjectScanner(ContextualMemoryPlugin.this);
            try {
                GhidraProjectScanner.ScanSummary summary = scanner.scan(project, path, mode, monitor);
                Msg.showInfo(this, tool.getToolFrame(), OWNER,
                        "%s complete.%n%nPrograms: %d%nFunctions: %d%nDecompiler failures: %d%nDatabase: %s"
                                .formatted(modeLabel(mode), summary.programs(), summary.functions(),
                                        summary.decompileFailures(), path));
            }
            catch (Exception e) {
                Msg.showError(this, tool.getToolFrame(), OWNER,
                        modeLabel(mode) + " failed", e);
            }
        }
    }

    private static String modeLabel(ScanMode mode) {
        return switch (mode) {
            case SCAN -> "Scan Project";
            case UPDATE -> "Update Project Database";
            case RESCAN -> "Rescan Project";
        };
    }
}
