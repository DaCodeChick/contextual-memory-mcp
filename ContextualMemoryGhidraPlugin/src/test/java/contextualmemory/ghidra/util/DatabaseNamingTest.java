package contextualmemory.ghidra.util;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class DatabaseNamingTest {
    @Test
    void createsPortableProjectDatabaseName() {
        assertEquals("ragnarok-online-2.sqlite",
                DatabaseNaming.databaseFileName("Ragnarök Online 2"));
    }

    @Test
    void preservesUsefulFilenameCharacters() {
        assertEquals("project-kdx_2026.1.sqlite",
                DatabaseNaming.databaseFileName("Project KDX_2026.1"));
    }

    @Test
    void rejectsBlankProjectName() {
        assertThrows(IllegalArgumentException.class,
                () -> DatabaseNaming.databaseFileName("  "));
    }
}
