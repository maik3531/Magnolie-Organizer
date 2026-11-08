package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class HardlinkEvidenceTest {
    private val source=StorageFileStat(1000,0x8180,3,1,5,123)
    private val linked=source.copy(links=2)
    private val directory=StorageFileStat(1000,0x41c0,4096,2,5,999)
    private fun reject(action:()->Unit) {try {action();fail("Unsafe fixture evidence accepted")}catch(_:IllegalStateException){}}
    @Test fun onlyObservedPermissionErrorsWithUntouchedSourceAndNoDestinationQualify() {
        for(errno in listOf(13,1)) HardlinkEvidence.denied(errno,source,source,null,true)
        for(errno in listOf(2,5,22,95)) reject {HardlinkEvidence.denied(errno,source,source,null,true)}
        reject {HardlinkEvidence.denied(13,source,source,source,true)}
        reject {HardlinkEvidence.denied(13,source,source.copy(inode=124),null,true)}
        reject {HardlinkEvidence.denied(13,source,source.copy(links=2),null,true)}
        reject {HardlinkEvidence.denied(13,source,source,null,false)}
    }
    @Test fun successfulCreationMustActuallyMakeTwoNamesForSameOwnedInode() {
        HardlinkEvidence.linked(source,linked,linked)
        reject {HardlinkEvidence.linked(source,source,source)}
        reject {HardlinkEvidence.linked(source,linked,linked.copy(inode=124))}
        reject {HardlinkEvidence.linked(source,linked,linked.copy(owner=2000))}
        reject {HardlinkEvidence.linked(source,linked,linked.copy(mode=0xa180))}
    }
    @Test fun unlinkIsBoundToRecordedDirectorySourceAndLinkIdentities() {
        HardlinkEvidence.cleanup(directory,directory,linked,linked,linked,linked)
        reject {HardlinkEvidence.cleanup(directory,directory.copy(inode=888),linked,linked,linked,linked)}
        reject {HardlinkEvidence.cleanup(directory,directory,linked,linked,linked,linked.copy(inode=124))}
        reject {HardlinkEvidence.cleanup(directory,directory,linked,linked,linked,linked.copy(owner=2000))}
        reject {HardlinkEvidence.cleanup(directory,directory,linked,linked.copy(links=3),linked,linked.copy(links=3))}
        reject {HardlinkEvidence.cleanup(directory,directory,linked,linked,linked,null)}
    }
}
