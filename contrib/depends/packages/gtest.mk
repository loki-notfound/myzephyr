package=gtest
$(package)_version=1.8.1
$(package)_download_path=https://github.com/google/googletest/archive/
$(package)_download_file=release-$($(package)_version).tar.gz
$(package)_file_name=$(package)-$($(package)_version).tar.gz
$(package)_sha256_hash=9bf1fe5182a604b4135edc1a425ae356c9ad15e9b23f9f12a02e80184c3a249c
$(package)_cxxflags=-std=c++11
$(package)_cxxflags_linux=-fPIC
# googletest's CMake appends DEBUG_POSTFIX "d" to its library names in Debug builds
$(package)_lib_postfix=$(if $(filter Debug,$(release_type)),d)

# The compiler and tools are the ones depends selected for the host, used as given
# (they may carry arguments, such as "g++-9 -m64"). They are looked up first in
# $(build_prefix)/bin, where depends installs its native tools, then in PATH; CMake
# needs absolute paths for AR and RANLIB.
define $(package)_config_cmds
  cd googletest && \
    export PATH="$(build_prefix)/bin:$$$$PATH" && \
    gtest_ar="$$$$(command -v $($(package)_ar))" && \
    gtest_ranlib="$$$$(command -v $($(package)_ranlib))" && \
    CC="$($(package)_cc)" \
    CXX="$($(package)_cxx)" \
    AR="$$$$gtest_ar" \
    RANLIB="$$$$gtest_ranlib" \
    LIBTOOL="$($(package)_libtool)" \
    CXXFLAGS="$($(package)_cxxflags)" \
    CCFLAGS="$($(package)_ccflags)" \
    CPPFLAGS="$($(package)_cppflags)" \
    CFLAGS="$($(package)_cflags) $($(package)_cppflags)" \
    LDLAGS="$($(package)_ldflags)" \
  cmake -DCMAKE_INSTALL_PREFIX=$(build_prefix) \
    -DTOOLCHAIN_PREFIX=$(host_toolchain) \
    -DCMAKE_AR="$$$$gtest_ar" \
    -DCMAKE_RANLIB="$$$$gtest_ranlib" \
    -DCMAKE_BUILD_TYPE=$(release_type)
endef
# -DCMAKE_TOOLCHAIN_FILE=$(HOST)/share/toolchain.cmake

define $(package)_build_cmds
  cd googletest && $(MAKE)
endef

define $(package)_stage_cmds
  mkdir $($(package)_staging_prefix_dir)/lib $($(package)_staging_prefix_dir)/include &&\
  cp googletest/libgtest$($(package)_lib_postfix).a $($(package)_staging_prefix_dir)/lib/libgtest.a &&\
  cp googletest/libgtest_main$($(package)_lib_postfix).a $($(package)_staging_prefix_dir)/lib/libgtest_main.a &&\
  cp -a googletest/include/* $($(package)_staging_prefix_dir)/include/
endef
