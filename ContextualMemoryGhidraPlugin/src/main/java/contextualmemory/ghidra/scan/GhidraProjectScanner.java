package contextualmemory.ghidra.scan;

import contextualmemory.ghidra.db.ProjectDatabase;
import contextualmemory.ghidra.util.Hashing;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.framework.model.DomainFile;
import ghidra.framework.model.DomainFolder;
import ghidra.framework.model.Project;
import ghidra.framework.model.ProjectData;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Program;
import ghidra.util.exception.CancelledException;
import ghidra.util.task.TaskMonitor;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.SQLException;
import java.util.HashSet;
import java.util.Set;

public final class GhidraProjectScanner {
    private static final int DECOMPILE_TIMEOUT_SECONDS = 60;

    private final Object consumer;

    public GhidraProjectScanner(Object consumer) {
        this.consumer = consumer;
    }

    public ScanSummary scan(Project project, Path databasePath, ScanMode mode, TaskMonitor monitor)
            throws IOException, SQLException, CancelledException {
        if (project == null) {
            throw new IllegalStateException("No Ghidra project is open");
        }

        return switch (mode) {
            case SCAN -> scanNew(project, databasePath, monitor);
            case UPDATE -> update(project, databasePath, monitor);
            case RESCAN -> rescan(project, databasePath, monitor);
        };
    }

    private ScanSummary scanNew(Project project, Path databasePath, TaskMonitor monitor)
            throws IOException, SQLException, CancelledException {
        if (Files.exists(databasePath)) {
            throw new IOException("Database already exists; use Update or Rescan: " + databasePath);
        }
        try (ProjectDatabase database = ProjectDatabase.create(databasePath)) {
            ScanSummary summary = scanInto(project, database, monitor);
            database.commitAndSeal();
            return summary;
        }
    }

    private ScanSummary update(Project project, Path databasePath, TaskMonitor monitor)
            throws IOException, SQLException, CancelledException {
        if (!Files.exists(databasePath)) {
            throw new IOException("Database does not exist; use Scan first: " + databasePath);
        }
        try (ProjectDatabase database = ProjectDatabase.openForUpdate(databasePath)) {
            ScanSummary summary = scanInto(project, database, monitor);
            database.commitAndSeal();
            return summary;
        }
    }

    private ScanSummary rescan(Project project, Path databasePath, TaskMonitor monitor)
            throws IOException, SQLException, CancelledException {
        Path temporary = databasePath.resolveSibling(databasePath.getFileName() + ".tmp");
        Files.deleteIfExists(temporary);
        try {
            ScanSummary summary;
            try (ProjectDatabase database = ProjectDatabase.create(temporary)) {
                summary = scanInto(project, database, monitor);
                database.commitAndSeal();
            }
            try {
                Files.move(temporary, databasePath, StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            }
            catch (java.nio.file.AtomicMoveNotSupportedException ignored) {
                Files.move(temporary, databasePath, StandardCopyOption.REPLACE_EXISTING);
            }
            databasePath.toFile().setWritable(false, false);
            return summary;
        }
        finally {
            Files.deleteIfExists(temporary);
        }
    }

    private ScanSummary scanInto(Project project, ProjectDatabase database, TaskMonitor monitor)
            throws SQLException, CancelledException {
        ProjectData projectData = project.getProjectData();
        Set<String> seenPrograms = new HashSet<>();
        MutableCounts counts = new MutableCounts();

        database.putMetadata("ghidra_project_name", project.getProjectLocator().getName());
        scanFolder(projectData.getRootFolder(), database, seenPrograms, counts, monitor);
        database.removeProgramsNotIn(seenPrograms);
        return new ScanSummary(counts.programs, counts.functions, counts.decompileFailures);
    }

    private void scanFolder(DomainFolder folder, ProjectDatabase database, Set<String> seenPrograms,
            MutableCounts counts, TaskMonitor monitor) throws CancelledException, SQLException {
        monitor.checkCancelled();
        for (DomainFile file : folder.getFiles()) {
            monitor.checkCancelled();
            scanFile(file, database, seenPrograms, counts, monitor);
        }
        for (DomainFolder child : folder.getFolders()) {
            scanFolder(child, database, seenPrograms, counts, monitor);
        }
    }

    private void scanFile(DomainFile file, ProjectDatabase database, Set<String> seenPrograms,
            MutableCounts counts, TaskMonitor monitor) throws CancelledException, SQLException {
        Object domainObject = null;
        try {
            domainObject = file.getDomainObject(consumer, false, false, monitor);
            if (!(domainObject instanceof Program program)) {
                return;
            }
            scanProgram(file, program, database, seenPrograms, counts, monitor);
        }
        catch (CancelledException e) {
            throw e;
        }
        catch (Exception e) {
            // Non-program domain files and damaged/unavailable files are intentionally skipped.
            counts.skippedFiles++;
        }
        finally {
            if (domainObject != null) {
                domainObject.getClass(); // keep nullability explicit before release
                ((ghidra.framework.model.DomainObject) domainObject).release(consumer);
            }
        }
    }

    private void scanProgram(DomainFile file, Program program, ProjectDatabase database,
            Set<String> seenPrograms, MutableCounts counts, TaskMonitor monitor)
            throws SQLException, CancelledException {
        String programId = programId(file, program);
        seenPrograms.add(programId);

        FunctionIterator functions = program.getFunctionManager().getFunctions(true);
        long functionCount = program.getFunctionManager().getFunctionCount();
        database.upsertProgram(new ProgramRecord(
                programId,
                file.getPathname(),
                program.getName(),
                emptyToNull(program.getExecutablePath()),
                emptyToNull(program.getExecutableMD5()),
                program.getLanguageID().getIdAsString(),
                program.getCompilerSpec().getCompilerSpecID().getIdAsString(),
                program.getImageBase().toString(),
                functionCount));
        database.deleteFunctionsForProgram(programId);

        monitor.setMessage("Scanning " + file.getPathname());
        try (DecompilerSession decompiler = new DecompilerSession(program)) {
            while (functions.hasNext()) {
                monitor.checkCancelled();
                Function function = functions.next();
                FunctionRecord record = createFunctionRecord(programId, function, decompiler, monitor,
                        counts);
                database.upsertFunction(record);
                counts.functions++;
            }
        }
        counts.programs++;
    }

    private FunctionRecord createFunctionRecord(String programId, Function function,
            DecompilerSession decompiler, TaskMonitor monitor, MutableCounts counts) {
        String decompiled = null;
        if (!function.isExternal()) {
            decompiled = decompiler.decompile(function, monitor);
            if (decompiled == null) {
                counts.decompileFailures++;
            }
        }

        String address = function.getEntryPoint().toString();
        String identity = Hashing.sha256(programId + ":function:" + address);
        String namespace = function.getParentNamespace().getName(true);
        String signature = function.getSignature().getPrototypeString();
        String comment = function.getComment();
        String content = String.join("\n",
                address,
                function.getName(),
                namespace,
                signature,
                nullToEmpty(function.getCallingConventionName()),
                nullToEmpty(comment),
                nullToEmpty(decompiled));

        return new FunctionRecord(
                programId,
                identity,
                address,
                function.getName(),
                namespace,
                signature,
                function.getCallingConventionName(),
                function.isExternal(),
                function.isThunk(),
                comment,
                decompiled,
                Hashing.sha256(content));
    }

    private static String programId(DomainFile file, Program program) {
        String executableHash = emptyToNull(program.getExecutableMD5());
        String stableSource = executableHash != null
                ? executableHash
                : file.getPathname() + "|" + program.getName();
        return Hashing.sha256(stableSource + "|" + program.getLanguageID().getIdAsString());
    }

    private static String emptyToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    public record ScanSummary(long programs, long functions, long decompileFailures) {
    }

    private static final class MutableCounts {
        long programs;
        long functions;
        long decompileFailures;
        long skippedFiles;
    }

    private static final class DecompilerSession implements AutoCloseable {
        private final DecompInterface decompiler = new DecompInterface();

        DecompilerSession(Program program) {
            decompiler.toggleCCode(true);
            decompiler.toggleSyntaxTree(false);
            if (!decompiler.openProgram(program)) {
                throw new IllegalStateException("Could not initialize the Ghidra decompiler");
            }
        }

        String decompile(Function function, TaskMonitor monitor) {
            DecompileResults results = decompiler.decompileFunction(
                    function, DECOMPILE_TIMEOUT_SECONDS, monitor);
            if (!results.decompileCompleted() || results.getDecompiledFunction() == null) {
                return null;
            }
            return results.getDecompiledFunction().getC();
        }

        @Override
        public void close() {
            decompiler.dispose();
        }
    }
}
