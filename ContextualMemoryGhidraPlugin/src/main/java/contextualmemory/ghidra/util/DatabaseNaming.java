package contextualmemory.ghidra.util;

import java.text.Normalizer;
import java.util.Locale;

public final class DatabaseNaming {
    private DatabaseNaming() {
    }

    public static String databaseFileName(String projectName) {
        if (projectName == null || projectName.isBlank()) {
            throw new IllegalArgumentException("Ghidra project name must not be blank");
        }

        String normalized = Normalizer.normalize(projectName, Normalizer.Form.NFKD)
                .replaceAll("\\p{M}+", "")
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9._-]+", "-")
                .replaceAll("-{2,}", "-")
                .replaceAll("^[._-]+|[._-]+$", "");

        if (normalized.isBlank()) {
            normalized = "ghidra-project";
        }
        return normalized + ".sqlite";
    }
}
