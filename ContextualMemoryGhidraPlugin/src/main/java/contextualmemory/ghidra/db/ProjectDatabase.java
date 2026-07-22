package contextualmemory.ghidra.db;

import contextualmemory.ghidra.scan.FunctionRecord;
import contextualmemory.ghidra.scan.ProgramRecord;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.util.Set;

public final class ProjectDatabase implements AutoCloseable {
    public static final int SCHEMA_VERSION = 1;

    private final Path path;
    private final Connection connection;

    private ProjectDatabase(Path path, Connection connection) {
        this.path = path;
        this.connection = connection;
    }

    public static ProjectDatabase create(Path path) throws SQLException, IOException {
        Files.createDirectories(path.toAbsolutePath().getParent());
        makeWritable(path);
        Connection connection = DriverManager.getConnection("jdbc:sqlite:" + path.toAbsolutePath());
        ProjectDatabase database = new ProjectDatabase(path, connection);
        database.configure();
        database.createSchema();
        database.connection.setAutoCommit(false);
        return database;
    }

    public static ProjectDatabase openForUpdate(Path path) throws SQLException, IOException {
        makeWritable(path);
        Connection connection = DriverManager.getConnection("jdbc:sqlite:" + path.toAbsolutePath());
        ProjectDatabase database = new ProjectDatabase(path, connection);
        database.configure();
        database.verifySchema();
        database.connection.setAutoCommit(false);
        return database;
    }

    private void configure() throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute("PRAGMA foreign_keys = ON");
            statement.execute("PRAGMA journal_mode = DELETE");
            statement.execute("PRAGMA synchronous = FULL");
        }
    }

    private void createSchema() throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """);
            statement.execute("""
                    CREATE TABLE programs (
                        program_id TEXT PRIMARY KEY,
                        project_path TEXT NOT NULL,
                        program_name TEXT NOT NULL,
                        executable_path TEXT,
                        executable_hash TEXT,
                        language_id TEXT NOT NULL,
                        compiler_spec_id TEXT NOT NULL,
                        image_base TEXT NOT NULL,
                        function_count INTEGER NOT NULL,
                        scanned_at TEXT NOT NULL
                    )
                    """);
            statement.execute("""
                    CREATE TABLE functions (
                        program_id TEXT NOT NULL REFERENCES programs(program_id) ON DELETE CASCADE,
                        identity_key TEXT NOT NULL,
                        entry_address TEXT NOT NULL,
                        name TEXT NOT NULL,
                        namespace TEXT NOT NULL,
                        signature TEXT NOT NULL,
                        calling_convention TEXT,
                        is_external INTEGER NOT NULL,
                        is_thunk INTEGER NOT NULL,
                        comment TEXT,
                        decompiled_c TEXT,
                        content_hash TEXT NOT NULL,
                        scanned_at TEXT NOT NULL,
                        PRIMARY KEY (program_id, identity_key)
                    )
                    """);
            statement.execute("CREATE INDEX functions_name_idx ON functions(name)");
            statement.execute("CREATE INDEX functions_hash_idx ON functions(content_hash)");
        }
        putMetadata("schema_version", Integer.toString(SCHEMA_VERSION));
        putMetadata("created_at", Instant.now().toString());
        putMetadata("producer", "ContextualMemoryGhidra");
    }

    private void verifySchema() throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT value FROM metadata WHERE key = 'schema_version'");
             var result = statement.executeQuery()) {
            if (!result.next() || result.getInt(1) != SCHEMA_VERSION) {
                throw new SQLException("Unsupported Contextual Memory Ghidra database schema");
            }
        }
    }

    public void putMetadata(String key, String value) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                INSERT INTO metadata(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """)) {
            statement.setString(1, key);
            statement.setString(2, value);
            statement.executeUpdate();
        }
    }

    public void upsertProgram(ProgramRecord program) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                INSERT INTO programs(program_id, project_path, program_name, executable_path,
                    executable_hash, language_id, compiler_spec_id, image_base, function_count, scanned_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(program_id) DO UPDATE SET
                    project_path=excluded.project_path,
                    program_name=excluded.program_name,
                    executable_path=excluded.executable_path,
                    executable_hash=excluded.executable_hash,
                    language_id=excluded.language_id,
                    compiler_spec_id=excluded.compiler_spec_id,
                    image_base=excluded.image_base,
                    function_count=excluded.function_count,
                    scanned_at=excluded.scanned_at
                """)) {
            statement.setString(1, program.programId());
            statement.setString(2, program.projectPath());
            statement.setString(3, program.programName());
            statement.setString(4, program.executablePath());
            statement.setString(5, program.executableHash());
            statement.setString(6, program.languageId());
            statement.setString(7, program.compilerSpecId());
            statement.setString(8, program.imageBase());
            statement.setLong(9, program.functionCount());
            statement.setString(10, Instant.now().toString());
            statement.executeUpdate();
        }
    }

    public void deleteFunctionsForProgram(String programId) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM functions WHERE program_id = ?")) {
            statement.setString(1, programId);
            statement.executeUpdate();
        }
    }

    public void upsertFunction(FunctionRecord function) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                INSERT INTO functions(program_id, identity_key, entry_address, name, namespace,
                    signature, calling_convention, is_external, is_thunk, comment, decompiled_c,
                    content_hash, scanned_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(program_id, identity_key) DO UPDATE SET
                    entry_address=excluded.entry_address,
                    name=excluded.name,
                    namespace=excluded.namespace,
                    signature=excluded.signature,
                    calling_convention=excluded.calling_convention,
                    is_external=excluded.is_external,
                    is_thunk=excluded.is_thunk,
                    comment=excluded.comment,
                    decompiled_c=excluded.decompiled_c,
                    content_hash=excluded.content_hash,
                    scanned_at=excluded.scanned_at
                """)) {
            statement.setString(1, function.programId());
            statement.setString(2, function.identityKey());
            statement.setString(3, function.entryAddress());
            statement.setString(4, function.name());
            statement.setString(5, function.namespace());
            statement.setString(6, function.signature());
            statement.setString(7, function.callingConvention());
            statement.setInt(8, function.external() ? 1 : 0);
            statement.setInt(9, function.thunk() ? 1 : 0);
            statement.setString(10, function.comment());
            statement.setString(11, function.decompiledC());
            statement.setString(12, function.contentHash());
            statement.setString(13, Instant.now().toString());
            statement.executeUpdate();
        }
    }

    public void removeProgramsNotIn(Set<String> programIds) throws SQLException {
        if (programIds.isEmpty()) {
            try (Statement statement = connection.createStatement()) {
                statement.executeUpdate("DELETE FROM programs");
            }
            return;
        }
        String placeholders = String.join(",", programIds.stream().map(id -> "?").toList());
        try (PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM programs WHERE program_id NOT IN (" + placeholders + ")")) {
            int index = 1;
            for (String id : programIds) {
                statement.setString(index++, id);
            }
            statement.executeUpdate();
        }
    }

    public void commitAndSeal() throws SQLException, IOException {
        putMetadata("updated_at", Instant.now().toString());
        connection.commit();
        connection.close();
        makeReadOnly(path);
    }

    public void rollbackQuietly() {
        try {
            connection.rollback();
        }
        catch (SQLException ignored) {
        }
    }

    @Override
    public void close() throws SQLException {
        if (!connection.isClosed()) {
            connection.close();
        }
    }

    private static void makeWritable(Path path) throws IOException {
        if (!Files.exists(path)) {
            return;
        }
        path.toFile().setWritable(true, true);
        try {
            Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path);
            permissions.add(PosixFilePermission.OWNER_WRITE);
            Files.setPosixFilePermissions(path, permissions);
        }
        catch (UnsupportedOperationException ignored) {
        }
    }

    private static void makeReadOnly(Path path) throws IOException {
        path.toFile().setWritable(false, false);
        try {
            Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path);
            permissions.remove(PosixFilePermission.OWNER_WRITE);
            permissions.remove(PosixFilePermission.GROUP_WRITE);
            permissions.remove(PosixFilePermission.OTHERS_WRITE);
            Files.setPosixFilePermissions(path, permissions);
        }
        catch (UnsupportedOperationException ignored) {
        }
    }
}
