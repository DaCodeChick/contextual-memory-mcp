package contextualmemory.ghidra.scan;

public record FunctionRecord(
        String programId,
        String identityKey,
        String entryAddress,
        String name,
        String namespace,
        String signature,
        String callingConvention,
        boolean external,
        boolean thunk,
        String comment,
        String decompiledC,
        String contentHash) {
}
