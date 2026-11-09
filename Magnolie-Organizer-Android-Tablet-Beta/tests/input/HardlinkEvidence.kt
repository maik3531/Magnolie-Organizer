package io.gitlab.maik3531.magnolietabletbeta

/** Test evidence policy, not an alternate production storage adapter. */
internal object HardlinkEvidence {
    fun denied(errno:Int,before:StorageFileStat,after:StorageFileStat?,destination:StorageFileStat?,bytesUnchanged:Boolean) {
        check(errno==13 || errno==1) {"Unexpected hardlink creation error"} // EACCES/EPERM only.
        check(before.isRegular && before.links==1L && after==before && destination==null && bytesUnchanged) {
            "Denied hardlink creation changed source or created destination"
        }
    }
    fun linked(before:StorageFileStat,source:StorageFileStat,link:StorageFileStat) {
        check(before.isRegular && before.links==1L && source.isRegular && link.isRegular &&
            before.sameFile(source) && source.sameFile(link) && source.links==2L && link.links==2L &&
            source.owner==before.owner && link.owner==before.owner && source.mode==before.mode &&
            link.mode==before.mode && source.size==before.size && link.size==before.size) {"Hardlink fixture identity mismatch"}
    }
    fun cleanup(directory:StorageFileStat,currentDirectory:StorageFileStat?,source:StorageFileStat,currentSource:StorageFileStat?,link:StorageFileStat,currentLink:StorageFileStat?) {
        check(currentDirectory!=null && directory.isDirectory && currentDirectory.isDirectory &&
            directory.sameFile(currentDirectory) && directory.owner==currentDirectory.owner && directory.mode==currentDirectory.mode &&
            currentSource!=null && currentLink!=null && currentSource.isRegular && currentLink.isRegular &&
            source.sameFile(currentSource) && link.sameFile(currentLink) && currentSource.sameFile(currentLink) &&
            source.owner==currentSource.owner && link.owner==currentLink.owner && source.mode==currentSource.mode &&
            link.mode==currentLink.mode && currentSource.links==2L && currentLink.links==2L) {"Refusing cleanup of changed hardlink identity"}
    }
}
