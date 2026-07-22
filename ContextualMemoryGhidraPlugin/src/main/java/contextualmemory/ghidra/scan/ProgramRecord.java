package contextualmemory.ghidra.scan;

public record ProgramRecord(
        String programId,
        String projectPath,
        String programName,
        String executablePath,
        String executableHash,
        String languageId,
        String compilerSpecId,
        String imageBase,
        long functionCount) {
}
